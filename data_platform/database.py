"""SQLite persistence with append-only market history and immutable executions."""

from __future__ import annotations

import sqlite3
import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator
from uuid import uuid4

from .domain import DecisionAction, ExecutionStatus, LedgerBook, SettlementOutcome
from .settlement import pnl_for


class IdempotencyConflictError(ValueError):
    """Raised when an idempotency key is reused for different evidence facts."""


EVIDENCE_FIELDS: dict[str, tuple[str, ...]] = {
    "fixture_context_observations": (
        "fixture_id", "competition_name", "country_code", "season", "competition_round",
        "venue_name", "neutral_venue", "referee_name", "provider", "source_reference",
        "observed_at_utc", "validation_status", "raw_payload_hash", "mapping_version", "idempotency_key",
    ),
    "team_metric_observations": (
        "fixture_id", "team_side", "metric_name", "metric_value", "unit", "period_start_utc",
        "period_end_utc", "sample_size", "provider", "source_reference", "observed_at_utc",
        "validation_status", "raw_payload_hash", "mapping_version", "idempotency_key",
    ),
    "player_availability_observations": (
        "fixture_id", "team_side", "player_reference", "player_name", "availability_status",
        "reported_reason", "source_confidence", "provider", "source_reference", "observed_at_utc",
        "validation_status", "raw_payload_hash", "mapping_version", "idempotency_key",
    ),
    "lineup_observations": (
        "fixture_id", "team_side", "player_reference", "player_name", "lineup_status", "position",
        "shirt_number", "provider", "source_reference", "observed_at_utc", "validation_status",
        "raw_payload_hash", "mapping_version", "idempotency_key",
    ),
}


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS fixtures (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    provider_fixture_id TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    kickoff_at_utc TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    UNIQUE(provider, provider_fixture_id)
);
CREATE TABLE IF NOT EXISTS market_snapshots (
    id TEXT PRIMARY KEY,
    fixture_id TEXT NOT NULL REFERENCES fixtures(id),
    provider TEXT NOT NULL,
    source_reference TEXT NOT NULL,
    market_type TEXT NOT NULL,
    settlement_type TEXT NOT NULL,
    selection TEXT NOT NULL,
    line REAL,
    decimal_odds REAL NOT NULL,
    observed_at_utc TEXT NOT NULL,
    fetched_at_utc TEXT NOT NULL,
    raw_payload_hash TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    mapping_version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analysis_decisions (
    id TEXT PRIMARY KEY,
    fixture_id TEXT NOT NULL REFERENCES fixtures(id),
    book TEXT NOT NULL CHECK(book IN ('analysis', 'counterfactual')),
    action TEXT NOT NULL CHECK(action IN ('BET', 'WATCH', 'PASS')),
    market_type TEXT NOT NULL,
    selection TEXT NOT NULL,
    line REAL,
    odds REAL,
    rating TEXT NOT NULL,
    ev REAL,
    created_at_utc TEXT NOT NULL,
    locked_at_utc TEXT,
    source_reference TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS executions (
    id TEXT PRIMARY KEY,
    fixture_id TEXT NOT NULL REFERENCES fixtures(id),
    market_type TEXT NOT NULL,
    settlement_type TEXT NOT NULL,
    selection TEXT NOT NULL,
    line REAL,
    odds REAL NOT NULL,
    rating TEXT NOT NULL,
    ev REAL NOT NULL,
    stake_u REAL NOT NULL CHECK(stake_u > 0),
    stake_cny REAL NOT NULL CHECK(stake_cny > 0),
    source_reference TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    locked_at_utc TEXT,
    status TEXT NOT NULL CHECK(status IN ('draft', 'locked', 'settled'))
);
CREATE TABLE IF NOT EXISTS settlements (
    id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL UNIQUE REFERENCES executions(id),
    outcome TEXT NOT NULL CHECK(outcome IN ('win', 'half_win', 'push', 'half_loss', 'loss')),
    result_payload_reference TEXT NOT NULL,
    settled_at_utc TEXT NOT NULL,
    pnl_u REAL NOT NULL,
    clv REAL
);
CREATE TABLE IF NOT EXISTS review_records (
    id TEXT PRIMARY KEY,
    book TEXT NOT NULL CHECK(book IN ('execution', 'analysis', 'counterfactual')),
    execution_id TEXT REFERENCES executions(id),
    decision_id TEXT REFERENCES analysis_decisions(id),
    classification TEXT,
    created_at_utc TEXT NOT NULL,
    notes TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_logs (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    payload_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS system_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bankroll_ledger (
    id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL REFERENCES executions(id),
    entry_type TEXT NOT NULL CHECK(entry_type IN ('stake', 'pnl')),
    amount_u REAL NOT NULL,
    created_at_utc TEXT NOT NULL,
    UNIQUE(execution_id, entry_type)
);
CREATE TABLE IF NOT EXISTS fixture_context_observations (
    id TEXT PRIMARY KEY, fixture_id TEXT NOT NULL REFERENCES fixtures(id), competition_name TEXT,
    country_code TEXT, season TEXT, competition_round TEXT, venue_name TEXT, neutral_venue INTEGER,
    referee_name TEXT, provider TEXT NOT NULL, source_reference TEXT NOT NULL,
    observed_at_utc TEXT NOT NULL, validation_status TEXT NOT NULL, raw_payload_hash TEXT NOT NULL,
    mapping_version TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS team_metric_observations (
    id TEXT PRIMARY KEY, fixture_id TEXT NOT NULL REFERENCES fixtures(id),
    team_side TEXT NOT NULL CHECK(team_side IN ('HOME', 'AWAY')), metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL, unit TEXT, period_start_utc TEXT, period_end_utc TEXT,
    sample_size INTEGER, provider TEXT NOT NULL, source_reference TEXT NOT NULL,
    observed_at_utc TEXT NOT NULL, validation_status TEXT NOT NULL, raw_payload_hash TEXT NOT NULL,
    mapping_version TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS player_availability_observations (
    id TEXT PRIMARY KEY, fixture_id TEXT NOT NULL REFERENCES fixtures(id),
    team_side TEXT NOT NULL CHECK(team_side IN ('HOME', 'AWAY')), player_reference TEXT,
    player_name TEXT, availability_status TEXT NOT NULL, reported_reason TEXT,
    source_confidence REAL, provider TEXT NOT NULL, source_reference TEXT NOT NULL,
    observed_at_utc TEXT NOT NULL, validation_status TEXT NOT NULL, raw_payload_hash TEXT NOT NULL,
    mapping_version TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS lineup_observations (
    id TEXT PRIMARY KEY, fixture_id TEXT NOT NULL REFERENCES fixtures(id),
    team_side TEXT NOT NULL CHECK(team_side IN ('HOME', 'AWAY')), player_reference TEXT,
    player_name TEXT, lineup_status TEXT NOT NULL CHECK(lineup_status IN ('STARTER', 'BENCH', 'OUT', 'UNKNOWN')),
    position TEXT, shirt_number INTEGER, provider TEXT NOT NULL, source_reference TEXT NOT NULL,
    observed_at_utc TEXT NOT NULL, validation_status TEXT NOT NULL, raw_payload_hash TEXT NOT NULL,
    mapping_version TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS source_documents (
    id TEXT PRIMARY KEY, source_type TEXT NOT NULL CHECK(source_type IN ('PUBLIC_HTML','PUBLIC_TEXT','JSON_LD','CSV_IMPORT','JSON_IMPORT','MANUAL_VERIFIED')),
    source_url TEXT NOT NULL, source_domain TEXT NOT NULL, retrieved_at_utc TEXT NOT NULL, published_at_utc TEXT,
    content_type TEXT NOT NULL, document_title TEXT, content_text TEXT NOT NULL, content_sha256 TEXT NOT NULL,
    parser_name TEXT, parser_version TEXT, validation_status TEXT NOT NULL, retrieval_method TEXT NOT NULL CHECK(retrieval_method IN ('WEB_FETCH','BROWSER_CAPTURE','FILE_IMPORT','MANUAL_ENTRY')),
    parent_document_id TEXT REFERENCES source_documents(id), idempotency_key TEXT NOT NULL UNIQUE
);
CREATE TRIGGER IF NOT EXISTS market_snapshots_are_append_only_update
BEFORE UPDATE ON market_snapshots
BEGIN SELECT RAISE(ABORT, 'market snapshots are append-only'); END;
CREATE TRIGGER IF NOT EXISTS market_snapshots_are_append_only_delete
BEFORE DELETE ON market_snapshots
BEGIN SELECT RAISE(ABORT, 'market snapshots are append-only'); END;
CREATE TRIGGER IF NOT EXISTS execution_must_be_created_pre_kickoff
BEFORE INSERT ON executions
WHEN NEW.created_at_utc >= (SELECT kickoff_at_utc FROM fixtures WHERE id = NEW.fixture_id)
BEGIN SELECT RAISE(ABORT, 'execution must be created before fixture kickoff'); END;
CREATE TRIGGER IF NOT EXISTS execution_starts_as_draft
BEFORE INSERT ON executions
WHEN NEW.status != 'draft' OR NEW.locked_at_utc IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'new execution must start as an unlocked draft'); END;
CREATE TRIGGER IF NOT EXISTS locked_execution_is_immutable
BEFORE UPDATE ON executions
WHEN OLD.locked_at_utc IS NOT NULL AND (
    NEW.fixture_id != OLD.fixture_id OR NEW.market_type != OLD.market_type OR
    NEW.settlement_type != OLD.settlement_type OR NEW.selection != OLD.selection OR
    NEW.line IS NOT OLD.line OR NEW.odds != OLD.odds OR NEW.rating != OLD.rating OR
    NEW.ev != OLD.ev OR NEW.stake_u != OLD.stake_u OR NEW.stake_cny != OLD.stake_cny OR
    NEW.source_reference != OLD.source_reference OR NEW.created_at_utc != OLD.created_at_utc OR
    NEW.locked_at_utc IS NOT OLD.locked_at_utc
)
BEGIN SELECT RAISE(ABORT, 'locked execution pre-match fields are immutable'); END;
CREATE TRIGGER IF NOT EXISTS execution_lock_must_precede_kickoff
BEFORE UPDATE ON executions
WHEN NEW.status = 'locked' AND (
    NEW.locked_at_utc IS NULL OR
    NEW.locked_at_utc >= (SELECT kickoff_at_utc FROM fixtures WHERE id = NEW.fixture_id)
)
BEGIN SELECT RAISE(ABORT, 'execution must be locked before fixture kickoff'); END;
CREATE TRIGGER IF NOT EXISTS execution_status_is_forward_only
BEFORE UPDATE OF status ON executions
WHEN NOT (
    (OLD.status = 'draft' AND NEW.status IN ('draft', 'locked')) OR
    (OLD.status = 'locked' AND NEW.status IN ('locked', 'settled')) OR
    (OLD.status = 'settled' AND NEW.status = 'settled')
)
BEGIN SELECT RAISE(ABORT, 'execution status transition is invalid'); END;
CREATE TRIGGER IF NOT EXISTS settlements_are_append_only_update
BEFORE UPDATE ON settlements
BEGIN SELECT RAISE(ABORT, 'settlements are append-only'); END;
CREATE TRIGGER IF NOT EXISTS settlements_are_append_only_delete
BEFORE DELETE ON settlements
BEGIN SELECT RAISE(ABORT, 'settlements are append-only'); END;
CREATE TRIGGER IF NOT EXISTS bankroll_ledger_is_append_only_update
BEFORE UPDATE ON bankroll_ledger
BEGIN SELECT RAISE(ABORT, 'bankroll ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS bankroll_ledger_is_append_only_delete
BEFORE DELETE ON bankroll_ledger
BEGIN SELECT RAISE(ABORT, 'bankroll ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS fixture_context_observations_append_only_update BEFORE UPDATE ON fixture_context_observations BEGIN SELECT RAISE(ABORT, 'fixture context observations are append-only'); END;
CREATE TRIGGER IF NOT EXISTS fixture_context_observations_append_only_delete BEFORE DELETE ON fixture_context_observations BEGIN SELECT RAISE(ABORT, 'fixture context observations are append-only'); END;
CREATE TRIGGER IF NOT EXISTS team_metric_observations_append_only_update BEFORE UPDATE ON team_metric_observations BEGIN SELECT RAISE(ABORT, 'team metric observations are append-only'); END;
CREATE TRIGGER IF NOT EXISTS team_metric_observations_append_only_delete BEFORE DELETE ON team_metric_observations BEGIN SELECT RAISE(ABORT, 'team metric observations are append-only'); END;
CREATE TRIGGER IF NOT EXISTS player_availability_observations_append_only_update BEFORE UPDATE ON player_availability_observations BEGIN SELECT RAISE(ABORT, 'player availability observations are append-only'); END;
CREATE TRIGGER IF NOT EXISTS player_availability_observations_append_only_delete BEFORE DELETE ON player_availability_observations BEGIN SELECT RAISE(ABORT, 'player availability observations are append-only'); END;
CREATE TRIGGER IF NOT EXISTS lineup_observations_append_only_update BEFORE UPDATE ON lineup_observations BEGIN SELECT RAISE(ABORT, 'lineup observations are append-only'); END;
CREATE TRIGGER IF NOT EXISTS lineup_observations_append_only_delete BEFORE DELETE ON lineup_observations BEGIN SELECT RAISE(ABORT, 'lineup observations are append-only'); END;
CREATE TRIGGER IF NOT EXISTS source_documents_append_only_update BEFORE UPDATE ON source_documents BEGIN SELECT RAISE(ABORT, 'source documents are append-only'); END;
CREATE TRIGGER IF NOT EXISTS source_documents_append_only_delete BEFORE DELETE ON source_documents BEGIN SELECT RAISE(ABORT, 'source documents are append-only'); END;
"""

TRIGGER_NAMES = (
    "market_snapshots_are_append_only_update",
    "market_snapshots_are_append_only_delete",
    "execution_must_be_created_pre_kickoff",
    "execution_starts_as_draft",
    "locked_execution_is_immutable",
    "execution_lock_must_precede_kickoff",
    "execution_status_is_forward_only",
    "settlements_are_append_only_update",
    "settlements_are_append_only_delete",
    "bankroll_ledger_is_append_only_update",
    "bankroll_ledger_is_append_only_delete",
    "fixture_context_observations_append_only_update", "fixture_context_observations_append_only_delete",
    "team_metric_observations_append_only_update", "team_metric_observations_append_only_delete",
    "player_availability_observations_append_only_update", "player_availability_observations_append_only_delete",
    "lineup_observations_append_only_update", "lineup_observations_append_only_delete",
    "source_documents_append_only_update", "source_documents_append_only_delete",
)

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_utc(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware UTC values")
    return parsed.astimezone(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str | Path, clock: Callable[[], str] = utc_now) -> None:
        self.path = str(path)
        self._clock = clock
        self.health_state = "UNVERIFIED"

    def _now(self) -> str:
        return normalize_utc(self._clock())

    @staticmethod
    def _kickoff_at(connection: sqlite3.Connection, fixture_id: str) -> str:
        fixture = connection.execute("SELECT kickoff_at_utc FROM fixtures WHERE id = ?", (fixture_id,)).fetchone()
        if fixture is None:
            raise ValueError("Fixture not found")
        return fixture["kickoff_at_utc"]

    def _require_pre_kickoff(self, connection: sqlite3.Connection, fixture_id: str, occurred_at_utc: str) -> str:
        timestamp = normalize_utc(occurred_at_utc)
        kickoff = self._kickoff_at(connection, fixture_id)
        if timestamp >= kickoff:
            raise ValueError("Formal Execution must be created and locked before fixture kickoff")
        return timestamp

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            # An empty path is a new database.  Any non-empty database without a
            # compatible version is deliberately left untouched: a future
            # migration must make that transition explicitly, with a backup.
            if not tables:
                connection.executescript(SCHEMA)
                connection.execute("INSERT INTO schema_version(version) VALUES (5)")
                return
            if "schema_version" not in tables:
                return
            versions = [row[0] for row in connection.execute("SELECT version FROM schema_version")]
            if versions in ([3], [4]):
                connection.executescript(SCHEMA)
                connection.execute("UPDATE schema_version SET version = 5")
                return
            if versions != [5]:
                return
            # A current-version database may receive repaired trigger bodies,
            # but initialization never rewrites its declared schema version.
            for trigger in TRIGGER_NAMES:
                connection.execute(f"DROP TRIGGER IF EXISTS {trigger}")
            connection.executescript(SCHEMA)

    @staticmethod
    def _evidence_text(value: object, name: str, *, allow_none: bool = False) -> str | None:
        if value is None and allow_none:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
        return value

    @staticmethod
    def _evidence_number(value: object, name: str, *, integer: bool = False, allow_none: bool = False) -> float | int | None:
        import math
        if value is None and allow_none:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number")
        if integer and int(value) != value:
            raise ValueError(f"{name} must be an integer")
        return int(value) if integer else float(value)

    @staticmethod
    def _default_idempotency_key(table: str, fields: dict[str, object], identity_fields: tuple[str, ...]) -> str:
        identity = {"evidence_type": table, **{key: fields.get(key) for key in identity_fields}}
        canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_idempotency_key(value: object) -> str:
        if isinstance(value, bool) or not isinstance(value, str) or not value.strip():
            raise ValueError("idempotency_key must be a non-empty string")
        return value.strip()

    def _append_evidence(self, table: str, fields: dict[str, object]) -> str:
        self._assert_writable()
        allowed = EVIDENCE_FIELDS[table]
        unknown = set(fields).difference(allowed)
        if unknown:
            raise ValueError(f"unsupported evidence fields: {sorted(unknown)}")
        fields = {field: fields.get(field) for field in allowed}
        for key in ("provider", "source_reference", "raw_payload_hash", "mapping_version", "validation_status"):
            self._evidence_text(fields.get(key), key)
        fields["observed_at_utc"] = normalize_utc(str(fields["observed_at_utc"]))
        fields["idempotency_key"] = self._validate_idempotency_key(fields.get("idempotency_key"))
        columns = allowed
        placeholders = ", ".join(f":{column}" for column in columns)
        observation_id = str(uuid4())
        try:
            with self.connection() as connection:
                connection.execute(
                    f"INSERT INTO {table} (id, {', '.join(columns)}) VALUES (:id, {placeholders})",
                    {"id": observation_id, **fields},
                )
        except sqlite3.IntegrityError as error:
            if "idempotency_key" in str(error):
                with self.connection() as connection:
                    row = connection.execute(f"SELECT * FROM {table} WHERE idempotency_key = ?", (fields["idempotency_key"],)).fetchone()
                if row is not None:
                    for field in allowed:
                        value = fields[field]
                        if row[field] != value:
                            raise IdempotencyConflictError(
                                f"idempotency_key conflicts with existing {table} evidence"
                            )
                    return str(row["id"])
            raise
        return observation_id

    def append_fixture_context(self, **fields: object) -> str:
        unknown = set(fields).difference(EVIDENCE_FIELDS["fixture_context_observations"])
        if unknown:
            raise ValueError(f"unsupported evidence fields: {sorted(unknown)}")
        fields = {field: fields.get(field) for field in EVIDENCE_FIELDS["fixture_context_observations"]}
        fields["observed_at_utc"] = normalize_utc(str(fields["observed_at_utc"]))
        if fields.get("neutral_venue") not in (None, True, False):
            raise ValueError("neutral_venue must be bool or None")
        if fields.get("neutral_venue") is not None:
            fields["neutral_venue"] = int(bool(fields["neutral_venue"]))
        if fields["idempotency_key"] is None:
            fields["idempotency_key"] = self._default_idempotency_key("fixture_context_observations", fields, ("fixture_id", "provider", "raw_payload_hash", "mapping_version", "observed_at_utc"))
        return self._append_evidence("fixture_context_observations", fields)

    def append_team_metric(self, **fields: object) -> str:
        unknown = set(fields).difference(EVIDENCE_FIELDS["team_metric_observations"])
        if unknown:
            raise ValueError(f"unsupported evidence fields: {sorted(unknown)}")
        fields = {field: fields.get(field) for field in EVIDENCE_FIELDS["team_metric_observations"]}
        fields["observed_at_utc"] = normalize_utc(str(fields["observed_at_utc"]))
        if fields.get("team_side") not in ("HOME", "AWAY"):
            raise ValueError("team_side must be HOME or AWAY")
        fields["metric_name"] = self._evidence_text(fields.get("metric_name"), "metric_name")
        fields["metric_value"] = self._evidence_number(fields.get("metric_value"), "metric_value")
        fields["sample_size"] = self._evidence_number(fields.get("sample_size"), "sample_size", integer=True, allow_none=True)
        for key in ("period_start_utc", "period_end_utc"):
            if fields.get(key) is not None:
                fields[key] = normalize_utc(str(fields[key]))
        if fields["idempotency_key"] is None:
            fields["idempotency_key"] = self._default_idempotency_key("team_metric_observations", fields, ("fixture_id", "provider", "raw_payload_hash", "mapping_version", "observed_at_utc", "team_side", "metric_name"))
        return self._append_evidence("team_metric_observations", fields)

    def append_player_availability(self, **fields: object) -> str:
        unknown = set(fields).difference(EVIDENCE_FIELDS["player_availability_observations"])
        if unknown:
            raise ValueError(f"unsupported evidence fields: {sorted(unknown)}")
        fields = {field: fields.get(field) for field in EVIDENCE_FIELDS["player_availability_observations"]}
        fields["observed_at_utc"] = normalize_utc(str(fields["observed_at_utc"]))
        if fields.get("team_side") not in ("HOME", "AWAY"):
            raise ValueError("team_side must be HOME or AWAY")
        fields["availability_status"] = self._evidence_text(fields.get("availability_status"), "availability_status")
        player_reference = self._evidence_text(fields.get("player_reference"), "player_reference", allow_none=True)
        player_name = self._evidence_text(fields.get("player_name"), "player_name", allow_none=True)
        if player_reference is None and player_name is None:
            raise ValueError("player_reference or player_name is required")
        fields["player_reference"], fields["player_name"] = player_reference, player_name
        fields["source_confidence"] = self._evidence_number(fields.get("source_confidence"), "source_confidence", allow_none=True)
        player_identity = player_reference if player_reference is not None else player_name
        fields["player_identity"] = player_identity
        if fields["idempotency_key"] is None:
            fields["idempotency_key"] = self._default_idempotency_key("player_availability_observations", fields, ("fixture_id", "provider", "raw_payload_hash", "mapping_version", "observed_at_utc", "team_side", "player_identity"))
        fields.pop("player_identity")
        return self._append_evidence("player_availability_observations", fields)

    def append_lineup(self, **fields: object) -> str:
        unknown = set(fields).difference(EVIDENCE_FIELDS["lineup_observations"])
        if unknown:
            raise ValueError(f"unsupported evidence fields: {sorted(unknown)}")
        fields = {field: fields.get(field) for field in EVIDENCE_FIELDS["lineup_observations"]}
        fields["observed_at_utc"] = normalize_utc(str(fields["observed_at_utc"]))
        if fields.get("team_side") not in ("HOME", "AWAY"):
            raise ValueError("team_side must be HOME or AWAY")
        if fields.get("lineup_status") not in ("STARTER", "BENCH", "OUT", "UNKNOWN"):
            raise ValueError("invalid lineup_status")
        player_reference = self._evidence_text(fields.get("player_reference"), "player_reference", allow_none=True)
        player_name = self._evidence_text(fields.get("player_name"), "player_name", allow_none=True)
        if player_reference is None and player_name is None:
            raise ValueError("player_reference or player_name is required")
        fields["player_reference"], fields["player_name"] = player_reference, player_name
        fields["shirt_number"] = self._evidence_number(fields.get("shirt_number"), "shirt_number", integer=True, allow_none=True)
        player_identity = player_reference if player_reference is not None else player_name
        fields["player_identity"] = player_identity
        if fields["idempotency_key"] is None:
            fields["idempotency_key"] = self._default_idempotency_key("lineup_observations", fields, ("fixture_id", "provider", "raw_payload_hash", "mapping_version", "observed_at_utc", "team_side", "player_identity", "lineup_status"))
        fields.pop("player_identity")
        return self._append_evidence("lineup_observations", fields)

    def record_audit(self, event_type: str, *, entity_type: str | None = None, entity_id: str | None = None, payload_json: str = "{}") -> None:
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO audit_logs VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid4()), event_type, entity_type, entity_id, payload_json, self._now()),
            )

    def require_recovery(self) -> None:
        self.health_state = "RECOVERY_REQUIRED"
        try:
            with self.connection() as connection:
                connection.execute("INSERT OR REPLACE INTO system_state VALUES ('database_health_state', 'RECOVERY_REQUIRED', ?)", (self._now(),))
        except sqlite3.DatabaseError:
            pass

    def mark_healthy(self, result: str = "passed") -> None:
        self.health_state = "HEALTHY"
        with self.connection() as connection:
            now = self._now()
            connection.execute("INSERT OR REPLACE INTO system_state VALUES ('database_health_state', 'HEALTHY', ?)", (now,))
            connection.execute("INSERT OR REPLACE INTO system_state VALUES ('last_integrity_check_at', ?, ?)", (now, now))
            connection.execute("INSERT OR REPLACE INTO system_state VALUES ('last_integrity_check_result', ?, ?)", (result, now))

    def _assert_writable(self) -> None:
        if self.health_state != "HEALTHY":
            raise RuntimeError(f"{self.health_state}: formal writes are blocked pending integrity verification")

    def create_fixture(self, *, provider: str, provider_fixture_id: str, home_team: str, away_team: str, kickoff_at_utc: str) -> str:
        fixture_id = str(uuid4())
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO fixtures VALUES (?, ?, ?, ?, ?, ?, ?)",
                (fixture_id, provider, provider_fixture_id, home_team, away_team, normalize_utc(kickoff_at_utc), self._now()),
            )
        return fixture_id

    def append_market_snapshot(self, **snapshot: object) -> str:
        """Snapshots are insert-only; callers must supply external source/provider metadata."""
        self._assert_writable()
        required = {"fixture_id", "provider", "source_reference", "market_type", "settlement_type", "selection", "decimal_odds", "observed_at_utc", "raw_payload_hash", "validation_status", "mapping_version"}
        missing = required.difference(snapshot)
        if missing:
            raise ValueError(f"market snapshot missing required fields: {sorted(missing)}")
        snapshot_id = str(uuid4())
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO market_snapshots VALUES (:id, :fixture_id, :provider, :source_reference, :market_type,
                :settlement_type, :selection, :line, :decimal_odds, :observed_at_utc, :fetched_at_utc,
                :raw_payload_hash, :validation_status, :mapping_version)""",
                {"id": snapshot_id, "line": None, "fetched_at_utc": self._now(), **snapshot},
            )
        return snapshot_id

    def create_analysis_decision(self, *, book: LedgerBook, action: DecisionAction, **fields: object) -> str:
        if book is LedgerBook.EXECUTION:
            raise ValueError("AnalysisDecision cannot be placed in the Execution Book")
        decision_id = str(uuid4())
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO analysis_decisions VALUES (:id, :fixture_id, :book, :action, :market_type, :selection,
                :line, :odds, :rating, :ev, :created_at_utc, :locked_at_utc, :source_reference)""",
                {"id": decision_id, "book": book.value, "action": action.value, "line": None, "odds": None,
                 "ev": None, "created_at_utc": self._now(), "locked_at_utc": None, **fields},
            )
        return decision_id

    def create_execution(self, *, action: DecisionAction, **fields: object) -> str:
        self._assert_writable()
        if action is not DecisionAction.BET:
            raise ValueError("Only an explicit pre-match BET can create an Execution")
        forbidden = {"created_at_utc", "locked_at_utc", "status"}.intersection(fields)
        if forbidden:
            raise ValueError(f"Execution lifecycle fields are system-managed: {sorted(forbidden)}")
        execution_id = str(uuid4())
        with self.connection() as connection:
            created_at_utc = self._require_pre_kickoff(connection, str(fields["fixture_id"]), self._now())
            connection.execute(
                """INSERT INTO executions VALUES (:id, :fixture_id, :market_type, :settlement_type, :selection, :line,
                :odds, :rating, :ev, :stake_u, :stake_cny, :source_reference, :created_at_utc, :locked_at_utc, :status)""",
                {"id": execution_id, "line": None, "created_at_utc": created_at_utc, "locked_at_utc": None,
                 "status": ExecutionStatus.DRAFT.value, **fields},
            )
        self.record_audit("execution_created", entity_type="execution", entity_id=execution_id)
        return execution_id

    def lock_execution(self, execution_id: str, locked_at_utc: str | None = None) -> None:
        self._assert_writable()
        with self.connection() as connection:
            execution = connection.execute("SELECT fixture_id, stake_u FROM executions WHERE id = ?", (execution_id,)).fetchone()
            if execution is None:
                raise ValueError("Execution is missing or already locked")
            lock_time = self._require_pre_kickoff(
                connection,
                execution["fixture_id"],
                locked_at_utc or self._now(),
            )
            result = connection.execute(
                "UPDATE executions SET locked_at_utc = ?, status = ? WHERE id = ? AND locked_at_utc IS NULL",
                (lock_time, ExecutionStatus.LOCKED.value, execution_id),
            )
            if result.rowcount != 1:
                raise ValueError("Execution is missing or already locked")
            connection.execute(
                "INSERT INTO bankroll_ledger VALUES (?, ?, 'stake', ?, ?)",
                (str(uuid4()), execution_id, -float(execution["stake_u"]), lock_time),
            )
        self.record_audit("execution_locked", entity_type="execution", entity_id=execution_id)

    def update_execution_draft(self, execution_id: str, **changes: object) -> None:
        allowed = {"fixture_id", "market_type", "settlement_type", "selection", "line", "odds", "rating", "ev", "stake_u", "stake_cny", "source_reference"}
        unknown = set(changes).difference(allowed)
        if unknown:
            raise ValueError(f"Cannot update fields: {sorted(unknown)}")
        with self.connection() as connection:
            row = connection.execute("SELECT locked_at_utc FROM executions WHERE id = ?", (execution_id,)).fetchone()
            if row is None:
                raise ValueError("Execution not found")
            if row["locked_at_utc"] is not None:
                raise ValueError("Locked execution pre-match fields are immutable")
            assignments = ", ".join(f"{field} = ?" for field in changes)
            connection.execute(f"UPDATE executions SET {assignments} WHERE id = ?", (*changes.values(), execution_id))

    def add_settlement(
        self,
        *,
        execution_id: str,
        outcome: SettlementOutcome,
        result_payload_reference: str,
        clv: float | None = None,
        expected_pnl_u: float | None = None,
    ) -> str:
        self._assert_writable()
        settlement_id = str(uuid4())
        with self.connection() as connection:
            existing = connection.execute(
                "SELECT id, outcome, result_payload_reference, clv FROM settlements WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            if existing is not None:
                same_clv = (existing["clv"] is None and clv is None) or (
                    existing["clv"] is not None and clv is not None and abs(float(existing["clv"]) - float(clv)) <= 1e-9
                )
                if (
                    existing["outcome"] == outcome.value
                    and existing["result_payload_reference"] == result_payload_reference
                    and same_clv
                ):
                    return existing["id"]
                raise ValueError("Conflicting settlement already exists for execution")
            row = connection.execute("SELECT status, stake_u, odds FROM executions WHERE id = ?", (execution_id,)).fetchone()
            if row is None or row["status"] != ExecutionStatus.LOCKED.value:
                raise ValueError("Only locked executions can be settled")
            calculated_pnl = pnl_for(row["stake_u"], row["odds"], outcome)
            if expected_pnl_u is not None and abs(expected_pnl_u - calculated_pnl) > 1e-9:
                raise ValueError("expected_pnl_u does not match system-calculated PnL")
            settled_at_utc = self._now()
            connection.execute("INSERT INTO settlements VALUES (?, ?, ?, ?, ?, ?, ?)", (settlement_id, execution_id, outcome.value, result_payload_reference, settled_at_utc, calculated_pnl, clv))
            connection.execute("INSERT INTO bankroll_ledger VALUES (?, ?, 'pnl', ?, ?)", (str(uuid4()), execution_id, calculated_pnl, settled_at_utc))
            connection.execute("UPDATE executions SET status = ? WHERE id = ?", (ExecutionStatus.SETTLED.value, execution_id))
        self.record_audit("settlement_created", entity_type="execution", entity_id=execution_id)
        return settlement_id

    def official_performance(self) -> dict[str, float]:
        """Only settled Execution Book entries contribute to formal PnL/ROI."""
        with self.connection() as connection:
            row = connection.execute(
                """SELECT COALESCE(SUM(s.pnl_u), 0) AS pnl, COALESCE(SUM(e.stake_u), 0) AS stake
                   FROM executions e JOIN settlements s ON s.execution_id = e.id
                   WHERE e.status = 'settled'"""
            ).fetchone()
        stake = float(row["stake"])
        pnl = float(row["pnl"])
        return {"pnl_u": pnl, "stake_u": stake, "roi": pnl / stake if stake else 0.0}
