"""Fail-closed SQLite backup, restore, and financial-fact reconciliation."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .database import Database
from .domain import SettlementOutcome
from .settlement import pnl_for

CURRENT_SCHEMA_VERSION = 5
APPLICATION_VERSION = "FQ-V6-005"
P0_TABLES = ("fixtures", "market_snapshots", "analysis_decisions", "executions", "settlements", "review_records", "bankroll_ledger", "audit_logs", "schema_version", "system_state", "fixture_context_observations", "team_metric_observations", "player_availability_observations", "lineup_observations", "ingestion_runs", "raw_provider_payloads", "ingested_snapshot_keys")
DIGEST_TABLES = P0_TABLES
REQUIRED_MANIFEST_FIELDS = {
    "backup_id", "database_path", "schema_version", "database_sha256",
    "table_row_counts", "table_digests", "official_performance", "created_at_utc", "manifest_version",
}
LOGGER = logging.getLogger(__name__)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rows(connection: sqlite3.Connection) -> dict[str, int]:
    return {table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in P0_TABLES}


def _table_digests(connection: sqlite3.Connection) -> dict[str, str]:
    """Hash canonical, primary-key ordered business facts, not SQLite pages."""
    digests: dict[str, str] = {}
    for table in DIGEST_TABLES:
        columns = [row["name"] for row in connection.execute(f"PRAGMA table_info({table})")]
        order_by = ", ".join(f'"{column}"' for column in columns)
        rows = connection.execute(f"SELECT * FROM {table} ORDER BY {order_by}").fetchall()
        payload = [{column: row[column] for column in columns} for row in rows]
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        digests[table] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return digests


def _different(left: float, right: float) -> bool:
    return abs(float(left) - float(right)) > 1e-9


def _execution_reconciliation(connection: sqlite3.Connection) -> tuple[list[str], float, float, float, int]:
    """Rebuild net PnL from immutable facts; stake is exposure, not a loss."""
    errors: list[str] = []
    expected_realized_pnl = 0.0
    exposure_u = 0.0
    settled_turnover_u = 0.0
    executions = connection.execute(
        """SELECT e.*, f.kickoff_at_utc, s.outcome, s.pnl_u AS settlement_pnl
           FROM executions e JOIN fixtures f ON f.id = e.fixture_id
           LEFT JOIN settlements s ON s.execution_id = e.id ORDER BY e.id"""
    ).fetchall()
    for execution in executions:
        execution_id = execution["id"]
        ledgers = connection.execute("SELECT entry_type, amount_u FROM bankroll_ledger WHERE execution_id = ? ORDER BY entry_type", (execution_id,)).fetchall()
        stake_entries = [row for row in ledgers if row["entry_type"] == "stake"]
        pnl_entries = [row for row in ledgers if row["entry_type"] == "pnl"]
        settlement_count = int(connection.execute("SELECT COUNT(*) FROM settlements WHERE execution_id = ?", (execution_id,)).fetchone()[0])
        status = execution["status"]
        if execution["created_at_utc"] >= execution["kickoff_at_utc"]:
            errors.append(f"{execution_id}: created_at_utc is not before kickoff")
        if status in ("locked", "settled"):
            if execution["locked_at_utc"] is None or execution["locked_at_utc"] >= execution["kickoff_at_utc"]:
                errors.append(f"{execution_id}: locked_at_utc is not before kickoff")
            if len(stake_entries) != 1:
                errors.append(f"{execution_id}: expected exactly one stake ledger")
            elif _different(stake_entries[0]["amount_u"], -float(execution["stake_u"])):
                errors.append(f"{execution_id}: stake ledger amount differs from immutable stake")
            else:
                exposure_u += float(execution["stake_u"])
        elif status == "draft":
            if stake_entries or settlement_count or pnl_entries:
                errors.append(f"{execution_id}: draft has formal financial facts")
        else:
            errors.append(f"{execution_id}: unsupported execution status")

        if status == "locked":
            if settlement_count != 0 or pnl_entries:
                errors.append(f"{execution_id}: locked execution has settlement facts")
        elif status == "settled":
            settled_turnover_u += float(execution["stake_u"])
            if settlement_count != 1 or len(pnl_entries) != 1:
                errors.append(f"{execution_id}: settled execution requires one settlement and one PnL ledger")
                continue
            expected_pnl = pnl_for(float(execution["stake_u"]), float(execution["odds"]), SettlementOutcome(execution["outcome"]))
            if _different(execution["settlement_pnl"], expected_pnl):
                errors.append(f"{execution_id}: settlement PnL differs from calculated outcome")
            if _different(pnl_entries[0]["amount_u"], expected_pnl):
                errors.append(f"{execution_id}: PnL ledger differs from calculated outcome")
            if not _different(execution["settlement_pnl"], expected_pnl) and not _different(pnl_entries[0]["amount_u"], expected_pnl):
                expected_realized_pnl += expected_pnl
        if status != "settled" and pnl_entries:
            errors.append(f"{execution_id}: non-settled execution has PnL ledger")
    return errors, expected_realized_pnl, exposure_u, settled_turnover_u, len(executions)


def _three_book_reconciliation(connection: sqlite3.Connection) -> list[str]:
    """Prove that review references cannot cross Analysis/Execution/Counterfactual books."""
    errors: list[str] = []
    rows = connection.execute(
        """SELECT r.id, r.book, r.execution_id, r.decision_id, d.book AS decision_book
           FROM review_records r
           LEFT JOIN analysis_decisions d ON d.id = r.decision_id
           ORDER BY r.id"""
    ).fetchall()
    for row in rows:
        if row["book"] == "execution":
            if row["execution_id"] is None or row["decision_id"] is not None:
                errors.append(f"{row['id']}: execution review has invalid book reference")
        elif row["book"] in ("analysis", "counterfactual"):
            if (
                row["decision_id"] is None
                or row["execution_id"] is not None
                or row["decision_book"] != row["book"]
            ):
                errors.append(f"{row['id']}: decision review crosses book boundary")
        else:
            errors.append(f"{row['id']}: unsupported review book")
    return errors


def _official_performance(connection: sqlite3.Connection) -> dict[str, float]:
    row = connection.execute(
        """SELECT COALESCE(SUM(s.pnl_u), 0) AS pnl, COALESCE(SUM(e.stake_u), 0) AS stake
           FROM executions e JOIN settlements s ON s.execution_id = e.id
           WHERE e.status = 'settled'"""
    ).fetchone()
    stake, pnl = float(row["stake"]), float(row["pnl"])
    return {"pnl_u": pnl, "stake_u": stake, "roi": pnl / stake if stake else 0.0}


@dataclass(frozen=True)
class IntegrityReport:
    ok: bool
    errors: tuple[str, ...]


def startup_integrity_check(database: Database, *, audit: bool = True) -> IntegrityReport:
    errors: list[str] = []
    previous_persisted_state: str | None = None
    if audit:
        try:
            database.record_audit("startup_integrity_check_started")
        except sqlite3.DatabaseError:
            LOGGER.exception("could not persist startup integrity audit event")
    try:
        with database.connection() as connection:
            state = connection.execute("SELECT value FROM system_state WHERE key='database_health_state'").fetchone()
            previous_persisted_state = state[0] if state is not None else None
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                errors.append("sqlite integrity_check failed")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                errors.append("foreign key check failed")
            try:
                versions = connection.execute("SELECT version FROM schema_version").fetchall()
            except sqlite3.DatabaseError:
                versions = []
            if len(versions) != 1 or versions[0][0] != CURRENT_SCHEMA_VERSION:
                errors.append("schema version is missing, unsupported, or migration is required")
            try:
                fact_errors, _, _, _, _ = _execution_reconciliation(connection)
                errors.extend(fact_errors)
                errors.extend(_three_book_reconciliation(connection))
                required_append_only = {
                    "market_snapshots_are_append_only_update", "market_snapshots_are_append_only_delete",
                    "settlements_are_append_only_update", "settlements_are_append_only_delete",
                    "bankroll_ledger_is_append_only_update", "bankroll_ledger_is_append_only_delete",
                }
                present = {
                    row[0] for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='trigger'"
                    )
                }
                missing = sorted(required_append_only.difference(present))
                if missing:
                    errors.append(f"append-only triggers missing: {missing}")
            except sqlite3.DatabaseError as error:
                errors.append(f"financial fact reconciliation failed: {error}")
    except sqlite3.DatabaseError as error:
        errors.append(f"database unavailable: {error}")
    if errors:
        database.require_recovery()
        if audit:
            try:
                database.record_audit("startup_integrity_check_failed", payload_json=json.dumps({"errors": errors}))
                database.record_audit("recovery_required_entered", payload_json=json.dumps({"errors": errors}))
            except sqlite3.DatabaseError:
                LOGGER.exception("could not persist recovery audit event")
    else:
        database.mark_healthy()
        if audit:
            database.record_audit("startup_integrity_check_passed")
            if previous_persisted_state == "RECOVERY_REQUIRED":
                database.record_audit("recovery_cleared")
    return IntegrityReport(ok=not errors, errors=tuple(errors))


def _fsync_file(path: Path) -> None:
    with path.open("r+b") as stream:
        os.fsync(stream.fileno())


def _fsync_directory(path: Path) -> bool:
    """Report unsupported directory fsync instead of pretending it succeeded."""
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return True
    except OSError as error:
        LOGGER.warning("directory fsync unsupported or failed for %s: %s", path, error)
        return False


def create_backup(database: Database, destination: Path, *, git_commit_sha: str | None = None, forensic_backup: bool = False) -> Path:
    """Use SQLite's backup API; never copy a live database file directly."""
    report = startup_integrity_check(database)
    if not report.ok and not forensic_backup:
        raise RuntimeError("RECOVERY_REQUIRED: normal backup refused")
    destination.mkdir(parents=True, exist_ok=True)
    backup_id = str(uuid4())
    database_file = destination / f"{backup_id}.sqlite3"
    manifest_file = destination / f"{backup_id}.manifest.json"
    database_tmp = destination / f"{backup_id}.sqlite3.tmp"
    manifest_tmp = destination / f"{backup_id}.manifest.json.tmp"
    try:
        database.record_audit("backup_started")
        target = sqlite3.connect(database_tmp)
        try:
            with database.connection() as source:
                source.backup(target)
        finally:
            target.close()
        _fsync_file(database_tmp)
        # Describe the immutable backup artifact itself, not a potentially later
        # live-database view after SQLite's consistent backup snapshot completed.
        backup_connection = sqlite3.connect(database_tmp)
        backup_connection.row_factory = sqlite3.Row
        try:
            row_counts, table_digests = _rows(backup_connection), _table_digests(backup_connection)
            official_performance = _official_performance(backup_connection)
            schema_version = backup_connection.execute("SELECT version FROM schema_version").fetchone()[0]
            last_locked = backup_connection.execute("SELECT MAX(locked_at_utc) FROM executions").fetchone()[0]
            last_settlement = backup_connection.execute("SELECT MAX(settled_at_utc) FROM settlements").fetchone()[0]
        finally:
            backup_connection.close()
        manifest = {"manifest_version": 1, "backup_id": backup_id, "created_at_utc": datetime.now(timezone.utc).isoformat(), "application_version": APPLICATION_VERSION, "database_path": database_file.name, "schema_version": schema_version, "git_commit_sha": git_commit_sha, "db_size": database_tmp.stat().st_size, "database_sha256": _sha256(database_tmp), "sqlite_version": sqlite3.sqlite_version, "health_status": database.health_state, "table_row_counts": row_counts, "table_digests": table_digests, "official_performance": official_performance, "last_execution_locked_at": last_locked, "last_settlement_at": last_settlement, "signature": None, "hmac": None}
        with manifest_tmp.open("w", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(database_tmp, database_file)
        _fsync_directory(destination)
        os.replace(manifest_tmp, manifest_file)
        _fsync_directory(destination)
        database.record_audit("backup_completed", payload_json=json.dumps({"backup_id": backup_id}))
        return manifest_file
    except Exception:
        database_tmp.unlink(missing_ok=True)
        manifest_tmp.unlink(missing_ok=True)
        try:
            database.record_audit("backup_failed", payload_json=json.dumps({"backup_id": backup_id}))
        except sqlite3.DatabaseError:
            LOGGER.exception("could not persist backup failure audit event")
        raise


def _validate_manifest(manifest: object) -> dict[str, object]:
    if not isinstance(manifest, dict) or not REQUIRED_MANIFEST_FIELDS.issubset(manifest):
        raise ValueError("backup manifest is incomplete")
    database_name = manifest["database_path"]
    if not isinstance(database_name, str):
        raise ValueError("manifest database_path is invalid")
    candidate = Path(database_name)
    if candidate.name != database_name or candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("manifest database_path must be a safe local filename")
    if not isinstance(manifest["table_row_counts"], dict) or not isinstance(manifest["table_digests"], dict):
        raise ValueError("manifest table metadata is invalid")
    if set(manifest["table_row_counts"]) != set(P0_TABLES) or set(manifest["table_digests"]) != set(DIGEST_TABLES):
        raise ValueError("manifest table metadata is incomplete")
    if manifest["schema_version"] != CURRENT_SCHEMA_VERSION:
        raise ValueError("manifest schema version is unsupported")
    return manifest


@dataclass(frozen=True)
class BackupCandidate:
    database_path: Path | None
    manifest_path: Path | None
    status: str
    reason: str
    created_at_utc: str | None = None


def _backup_schema_is_supported(database_path: Path) -> bool:
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(database_path)
        versions = connection.execute("SELECT version FROM schema_version").fetchall()
        return len(versions) == 1 and versions[0][0] == CURRENT_SCHEMA_VERSION
    except sqlite3.DatabaseError:
        return False
    finally:
        if connection is not None:
            connection.close()


def list_backups(destination: Path) -> tuple[BackupCandidate, ...]:
    """Inventory only; orphaned databases and temporary files are never deleted."""
    if not destination.exists():
        return ()
    candidates: list[BackupCandidate] = []
    consumed: set[Path] = set()
    for manifest_path in sorted(destination.glob("*.manifest.json")):
        try:
            manifest = _validate_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
            database_path = manifest_path.parent / str(manifest["database_path"])
            if not database_path.is_file():
                candidates.append(BackupCandidate(database_path, manifest_path, "INCOMPLETE", "database file is missing"))
            elif _sha256(database_path) != manifest["database_sha256"]:
                candidates.append(BackupCandidate(database_path, manifest_path, "INVALID", "database checksum mismatch"))
            elif not _backup_schema_is_supported(database_path):
                candidates.append(BackupCandidate(database_path, manifest_path, "INVALID", "database schema is unsupported"))
            else:
                candidates.append(BackupCandidate(database_path, manifest_path, "VALID", "verified", str(manifest["created_at_utc"])))
            consumed.add(database_path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            candidates.append(BackupCandidate(None, manifest_path, "INVALID", f"invalid manifest: {error}"))
    for database_path in sorted(destination.glob("*.sqlite3")):
        if database_path not in consumed:
            candidates.append(BackupCandidate(database_path, None, "INCOMPLETE", "manifest is missing"))
    for temporary_path in sorted(destination.glob("*.tmp")):
        candidates.append(BackupCandidate(None, temporary_path, "INCOMPLETE", "temporary publication artifact"))
    return tuple(candidates)


def find_latest_valid_backup(destination: Path) -> BackupCandidate | None:
    valid = [item for item in list_backups(destination) if item.status == "VALID"]
    return max(valid, key=lambda item: item.created_at_utc or "") if valid else None


def restore_backup(manifest_path: Path, target_path: Path) -> Database:
    """Restore to a temporary path; publish only after all verification passes."""
    manifest = _validate_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
    source = manifest_path.parent / str(manifest["database_path"])
    if not source.is_file() or _sha256(source) != manifest["database_sha256"]:
        raise ValueError("backup checksum mismatch")
    if target_path.exists():
        raise ValueError("restore target must be a new database path")
    restore_tmp = Path(f"{target_path}.restore_tmp")
    if restore_tmp.exists():
        raise ValueError("restore temporary path already exists")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    published = False
    try:
        source_connection = sqlite3.connect(source)
        target_connection = sqlite3.connect(restore_tmp)
        try:
            source_connection.backup(target_connection)
        finally:
            target_connection.close()
            source_connection.close()
        restored = Database(restore_tmp)
        with restored.connection() as connection:
            if _rows(connection) != manifest["table_row_counts"]:
                raise ValueError("restored row counts do not match manifest")
            if _table_digests(connection) != manifest["table_digests"]:
                raise ValueError("restored table digests do not match manifest")
            restored_performance = _official_performance(connection)
            expected_performance = manifest["official_performance"]
            if not isinstance(expected_performance, dict) or any(
                key not in expected_performance or _different(restored_performance[key], expected_performance[key])
                for key in ("pnl_u", "stake_u", "roi")
            ):
                raise ValueError("restored ROI/PnL does not match backup manifest")
        report = startup_integrity_check(restored, audit=False)
        if not report.ok:
            raise ValueError(f"restored database failed integrity check: {report.errors}")
        restored.record_audit("restore_started", payload_json=json.dumps({"backup_id": manifest["backup_id"]}))
        _fsync_file(restore_tmp)
        os.replace(restore_tmp, target_path)
        published = True
        _fsync_directory(target_path.parent)
        final = Database(target_path)
        final_report = startup_integrity_check(final, audit=False)
        if not final_report.ok or any(
            _different(final.official_performance()[key], manifest["official_performance"][key])
            for key in ("pnl_u", "stake_u", "roi")
        ):
            raise RuntimeError("published restore failed final reopen verification")
        final.record_audit("restore_completed", payload_json=json.dumps({"backup_id": manifest["backup_id"]}))
        return final
    except Exception:
        restore_tmp.unlink(missing_ok=True)
        if published:
            target_path.unlink(missing_ok=True)
        LOGGER.exception("restore failed")
        raise


def rebuild_bankroll(database: Database, *, initial_bankroll_u: float = 100.0) -> dict[str, object]:
    """Net-PnL balance: stake ledger records exposure/turnover, not a loss."""
    with database.connection() as connection:
        mismatches, realized_pnl, exposure_u, turnover_u, executions_checked = _execution_reconciliation(connection)
        official = _official_performance(connection)
        if _different(official["pnl_u"], realized_pnl):
            mismatches.append("official performance PnL differs from immutable fact rebuild")
        if _different(official["stake_u"], turnover_u):
            mismatches.append("official performance turnover differs from immutable execution stakes")
    balance = float(initial_bankroll_u) + realized_pnl
    result = {"initial_bankroll_u": float(initial_bankroll_u), "balance_u": round(balance, 10), "rebuilt_balance_u": round(balance, 10), "realized_pnl_u": round(realized_pnl, 10), "turnover_u": round(turnover_u, 10), "exposure_u": round(exposure_u, 10), "roi": round(realized_pnl / turnover_u, 10) if turnover_u else 0.0, "executions_checked": executions_checked, "mismatches": tuple(mismatches)}
    if mismatches:
        database.require_recovery()
        raise ValueError(f"bankroll reconciliation failed: {mismatches}")
    return result
