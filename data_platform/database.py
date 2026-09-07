"""SQLite persistence with append-only market history and immutable executions."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from .domain import DecisionAction, ExecutionStatus, LedgerBook, SettlementOutcome


SCHEMA = """
PRAGMA foreign_keys = ON;
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
CREATE TABLE IF NOT EXISTS bankroll_ledger (
    id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL REFERENCES executions(id),
    entry_type TEXT NOT NULL CHECK(entry_type IN ('stake', 'pnl')),
    amount_u REAL NOT NULL,
    created_at_utc TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS locked_execution_is_immutable
BEFORE UPDATE ON executions
WHEN OLD.locked_at_utc IS NOT NULL AND (
    NEW.fixture_id != OLD.fixture_id OR NEW.market_type != OLD.market_type OR
    NEW.settlement_type != OLD.settlement_type OR NEW.selection != OLD.selection OR
    NEW.line IS NOT OLD.line OR NEW.odds != OLD.odds OR NEW.rating != OLD.rating OR
    NEW.ev != OLD.ev OR NEW.stake_u != OLD.stake_u OR NEW.created_at_utc != OLD.created_at_utc OR
    NEW.locked_at_utc IS NOT OLD.locked_at_utc
)
BEGIN SELECT RAISE(ABORT, 'locked execution pre-match fields are immutable'); END;
CREATE TRIGGER IF NOT EXISTS execution_must_stay_execution_book
BEFORE INSERT ON executions
WHEN NEW.status NOT IN ('draft', 'locked', 'settled')
BEGIN SELECT RAISE(ABORT, 'invalid execution status'); END;
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as connection:
            connection.executescript(SCHEMA)

    def create_fixture(self, *, provider: str, provider_fixture_id: str, home_team: str, away_team: str, kickoff_at_utc: str) -> str:
        fixture_id = str(uuid4())
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO fixtures VALUES (?, ?, ?, ?, ?, ?, ?)",
                (fixture_id, provider, provider_fixture_id, home_team, away_team, kickoff_at_utc, utc_now()),
            )
        return fixture_id

    def append_market_snapshot(self, **snapshot: object) -> str:
        """Snapshots are insert-only; callers must supply external source/provider metadata."""
        required = {"fixture_id", "provider", "source_reference", "market_type", "settlement_type", "selection", "decimal_odds", "observed_at_utc", "raw_payload_hash", "validation_status", "mapping_version"}
        missing = required.difference(snapshot)
        if missing:
            raise ValueError(f"market snapshot missing required fields: {sorted(missing)}")
        snapshot_id = str(uuid4())
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO market_snapshots VALUES (?, :fixture_id, :provider, :source_reference, :market_type,
                :settlement_type, :selection, :line, :decimal_odds, :observed_at_utc, :fetched_at_utc,
                :raw_payload_hash, :validation_status, :mapping_version)""",
                {"id": snapshot_id, "line": None, "fetched_at_utc": utc_now(), **snapshot},
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
                 "ev": None, "created_at_utc": utc_now(), "locked_at_utc": None, **fields},
            )
        return decision_id

    def create_execution(self, *, action: DecisionAction, **fields: object) -> str:
        if action is not DecisionAction.BET:
            raise ValueError("Only an explicit pre-match BET can create an Execution")
        execution_id = str(uuid4())
        stake_u = float(fields["stake_u"])
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO executions VALUES (:id, :fixture_id, :market_type, :settlement_type, :selection, :line,
                :odds, :rating, :ev, :stake_u, :stake_cny, :source_reference, :created_at_utc, :locked_at_utc, :status)""",
                {"id": execution_id, "line": None, "created_at_utc": utc_now(), "locked_at_utc": None,
                 "status": ExecutionStatus.DRAFT.value, **fields},
            )
            connection.execute("INSERT INTO bankroll_ledger VALUES (?, ?, 'stake', ?, ?)", (str(uuid4()), execution_id, -stake_u, utc_now()))
        return execution_id

    def lock_execution(self, execution_id: str, locked_at_utc: str | None = None) -> None:
        with self.connection() as connection:
            result = connection.execute(
                "UPDATE executions SET locked_at_utc = ?, status = ? WHERE id = ? AND locked_at_utc IS NULL",
                (locked_at_utc or utc_now(), ExecutionStatus.LOCKED.value, execution_id),
            )
            if result.rowcount != 1:
                raise ValueError("Execution is missing or already locked")

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

    def add_settlement(self, *, execution_id: str, outcome: SettlementOutcome, result_payload_reference: str, pnl_u: float, clv: float | None = None) -> str:
        settlement_id = str(uuid4())
        with self.connection() as connection:
            row = connection.execute("SELECT status FROM executions WHERE id = ?", (execution_id,)).fetchone()
            if row is None or row["status"] != ExecutionStatus.LOCKED.value:
                raise ValueError("Only locked executions can be settled")
            connection.execute("INSERT INTO settlements VALUES (?, ?, ?, ?, ?, ?, ?)", (settlement_id, execution_id, outcome.value, result_payload_reference, utc_now(), pnl_u, clv))
            connection.execute("INSERT INTO bankroll_ledger VALUES (?, ?, 'pnl', ?, ?)", (str(uuid4()), execution_id, pnl_u, utc_now()))
            connection.execute("UPDATE executions SET status = ? WHERE id = ?", (ExecutionStatus.SETTLED.value, execution_id))
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
