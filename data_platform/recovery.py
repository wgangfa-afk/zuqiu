"""Single-host SQLite backup, restore and startup integrity controls."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .database import Database


CURRENT_SCHEMA_VERSION = 3
P0_TABLES = ("fixtures", "market_snapshots", "analysis_decisions", "executions", "settlements", "review_records", "bankroll_ledger", "audit_logs", "schema_version", "system_state")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rows(connection: sqlite3.Connection) -> dict[str, int]:
    return {table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in P0_TABLES}


@dataclass(frozen=True)
class IntegrityReport:
    ok: bool
    errors: tuple[str, ...]


def startup_integrity_check(database: Database, *, audit: bool = True) -> IntegrityReport:
    errors: list[str] = []
    if audit:
        try:
            database.record_audit("startup_integrity_check_started")
        except sqlite3.DatabaseError:
            pass
    try:
        with database.connection() as connection:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                errors.append("sqlite integrity_check failed")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                errors.append("foreign key check failed")
            versions = connection.execute("SELECT version FROM schema_version").fetchall()
            if len(versions) != 1 or versions[0][0] != CURRENT_SCHEMA_VERSION:
                errors.append("schema version is missing, unsupported, or migration is required")
            bad = connection.execute("""
                SELECT id FROM executions e WHERE
                (status IN ('locked','settled') AND (SELECT COUNT(*) FROM bankroll_ledger l WHERE l.execution_id=e.id AND l.entry_type='stake') != 1)
                OR (status='settled' AND ((SELECT COUNT(*) FROM settlements s WHERE s.execution_id=e.id) != 1 OR (SELECT COUNT(*) FROM bankroll_ledger l WHERE l.execution_id=e.id AND l.entry_type='pnl') != 1))
                OR (status='locked' AND (SELECT COUNT(*) FROM settlements s WHERE s.execution_id=e.id) != 0)
            """).fetchall()
            if bad:
                errors.append("execution lifecycle or ledger invariant failed")
            trigger_count = connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'market_snapshots_are_append_only_%'").fetchone()[0]
            if trigger_count != 2:
                errors.append("market snapshot append-only triggers missing")
    except sqlite3.DatabaseError as error:
        errors.append(f"database unavailable: {error}")
    if errors:
        database.require_recovery()
        if audit:
            try:
                database.record_audit("startup_integrity_check_failed", payload_json=json.dumps({"errors": errors}))
                database.record_audit("recovery_required_entered", payload_json=json.dumps({"errors": errors}))
            except sqlite3.DatabaseError:
                pass
    else:
        database.mark_healthy()
        if audit:
            database.record_audit("startup_integrity_check_passed")
    return IntegrityReport(ok=not errors, errors=tuple(errors))


def create_backup(database: Database, destination: Path, *, git_commit_sha: str | None = None, forensic_backup: bool = False) -> Path:
    """Use SQLite's backup API; never copy a live database file directly."""
    report = startup_integrity_check(database)
    if not report.ok and not forensic_backup:
        raise RuntimeError("RECOVERY_REQUIRED: normal backup refused")
    destination.mkdir(parents=True, exist_ok=True)
    database.record_audit("backup_started")
    backup_id = str(uuid4())
    database_file = destination / f"{backup_id}.sqlite3"
    manifest_file = destination / f"{backup_id}.manifest.json"
    database_tmp = destination / f"{backup_id}.sqlite3.tmp"
    manifest_tmp = destination / f"{backup_id}.manifest.json.tmp"
    target = sqlite3.connect(database_tmp)
    with database.connection() as source:
        source.backup(target)
        row_counts = _rows(source)
        schema_version = source.execute("SELECT version FROM schema_version").fetchone()[0]
        last_locked = source.execute("SELECT MAX(locked_at_utc) FROM executions").fetchone()[0]
        last_settlement = source.execute("SELECT MAX(settled_at_utc) FROM settlements").fetchone()[0]
    target.close()
    manifest = {
        "backup_id": backup_id, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "application_version": "FQ-V6-002", "database_path": database_file.name, "schema_version": schema_version, "git_commit_sha": git_commit_sha,
        "db_size": database_tmp.stat().st_size, "database_sha256": _sha256(database_tmp), "sqlite_version": sqlite3.sqlite_version,
        "health_status": database.health_state, "table_row_counts": row_counts,
        "last_execution_locked_at": last_locked, "last_settlement_at": last_settlement,
    }
    manifest_tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    with manifest_tmp.open("rb") as stream:
        stream.flush() if hasattr(stream, "flush") else None
    database_tmp.replace(database_file)
    manifest_tmp.replace(manifest_file)
    database.record_audit("backup_completed", payload_json=json.dumps({"backup_id": backup_id}))
    return manifest_file


def restore_backup(manifest_path: Path, target_path: Path) -> Database:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source = manifest_path.parent / manifest["database_path"]
    if _sha256(source) != manifest["database_sha256"]:
        raise ValueError("backup checksum mismatch")
    if target_path.exists():
        raise ValueError("restore target must be a new database path")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as source_connection, sqlite3.connect(target_path) as target_connection:
        source_connection.backup(target_connection)
    restored = Database(target_path)
    report = startup_integrity_check(restored, audit=False)
    if not report.ok:
        raise ValueError(f"restored database failed integrity check: {report.errors}")
    with restored.connection() as connection:
        if _rows(connection) != manifest["table_row_counts"]:
            raise ValueError("restored row counts do not match manifest")
    restored.record_audit("restore_completed", payload_json=json.dumps({"backup_id": manifest["backup_id"]}))
    return restored


def rebuild_bankroll(database: Database) -> dict[str, float]:
    with database.connection() as connection:
        ledger = float(connection.execute("SELECT COALESCE(SUM(amount_u), 0) FROM bankroll_ledger").fetchone()[0])
        expected = float(connection.execute("""
            SELECT COALESCE(SUM(CASE WHEN e.status IN ('locked','settled') THEN -e.stake_u ELSE 0 END), 0)
                 + COALESCE((SELECT SUM(pnl_u) FROM settlements), 0) FROM executions e
        """).fetchone()[0])
    if abs(ledger - expected) > 1e-9:
        database.require_recovery()
        raise ValueError("bankroll ledger does not match rebuilt balance")
    return {"balance_u": round(ledger, 10), "rebuilt_balance_u": round(expected, 10)}
