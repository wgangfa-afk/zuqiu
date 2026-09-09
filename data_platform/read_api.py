"""Restricted, typed, read-only contract for the Analysis Engine."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .database import Database
from .domain import DecisionAction, ExecutionStatus, LedgerBook, SettlementOutcome
from .read_models import (
    AnalysisDecisionRecord, ExecutionRecord, FixtureContextRecord, FixtureRecord, LineupRecord,
    MarketSnapshotRecord, PlayerAvailabilityRecord, SettlementRecord, TeamMetricRecord,
)


class RecordNotFoundError(LookupError):
    """Raised when a required public record does not exist."""


class InvalidReadFilterError(ValueError):
    """Raised for an invalid bounded list filter."""


class DatabaseNotHealthyError(RuntimeError):
    """Raised when public Analysis reads use an unverified database."""


def _utc_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("stored timestamp is unexpectedly timezone-naive")
    return parsed.astimezone(timezone.utc)


def _require_utc(value: datetime | None, name: str) -> str | None:
    if value is None:
        return None
    if value.tzinfo is not timezone.utc:
        raise InvalidReadFilterError(f"{name} must be a UTC timezone-aware datetime")
    return value.isoformat()


class ReadRepository:
    """Typed read facade. No method mutates data or alters health state."""

    def __init__(self, database: Database) -> None:
        self._database = database
        self._require_healthy()

    def _require_healthy(self) -> None:
        if self._database.health_state != "HEALTHY":
            raise DatabaseNotHealthyError(f"database is {self._database.health_state}; public reads require HEALTHY")

    @staticmethod
    def _limit(limit: int) -> int:
        if not 1 <= limit <= 5000:
            raise InvalidReadFilterError("limit must be between 1 and 5000")
        return limit

    @staticmethod
    def _fixture(row: Any) -> FixtureRecord:
        return FixtureRecord(row["id"], row["provider"], row["provider_fixture_id"], row["home_team"], row["away_team"], _utc_datetime(row["kickoff_at_utc"]), _utc_datetime(row["created_at_utc"]))

    @staticmethod
    def _snapshot(row: Any) -> MarketSnapshotRecord:
        return MarketSnapshotRecord(row["id"], row["fixture_id"], row["provider"], row["source_reference"], row["market_type"], row["settlement_type"], row["selection"], row["line"], row["decimal_odds"], _utc_datetime(row["observed_at_utc"]), _utc_datetime(row["fetched_at_utc"]), row["raw_payload_hash"], row["validation_status"], row["mapping_version"])

    @staticmethod
    def _decision(row: Any) -> AnalysisDecisionRecord:
        return AnalysisDecisionRecord(row["id"], row["fixture_id"], LedgerBook(row["book"]), DecisionAction(row["action"]), row["market_type"], row["selection"], row["line"], row["odds"], row["rating"], row["ev"], _utc_datetime(row["created_at_utc"]), _utc_datetime(row["locked_at_utc"]), row["source_reference"])

    @staticmethod
    def _execution(row: Any) -> ExecutionRecord:
        return ExecutionRecord(row["id"], row["fixture_id"], row["market_type"], row["settlement_type"], row["selection"], row["line"], row["odds"], row["rating"], row["ev"], row["stake_u"], row["stake_cny"], row["source_reference"], _utc_datetime(row["created_at_utc"]), _utc_datetime(row["locked_at_utc"]), ExecutionStatus(row["status"]))

    @staticmethod
    def _settlement(row: Any) -> SettlementRecord:
        return SettlementRecord(row["id"], row["execution_id"], SettlementOutcome(row["outcome"]), row["result_payload_reference"], _utc_datetime(row["settled_at_utc"]), row["pnl_u"], row["clv"])

    def get_fixture(self, fixture_id: str) -> FixtureRecord:
        self._require_healthy()
        with self._database.connection() as connection:
            row = connection.execute("SELECT * FROM fixtures WHERE id = ?", (fixture_id,)).fetchone()
        if row is None:
            raise RecordNotFoundError(f"fixture not found: {fixture_id}")
        return self._fixture(row)

    def list_market_snapshots(self, fixture_id: str, *, market_type: str | None = None, provider: str | None = None, validation_status: str | None = None, observed_from_utc: datetime | None = None, observed_to_utc: datetime | None = None, limit: int = 1000) -> tuple[MarketSnapshotRecord, ...]:
        self._require_healthy()
        clauses, values = ["fixture_id = ?"], [fixture_id]
        for clause, value in (("market_type", market_type), ("provider", provider), ("validation_status", validation_status)):
            if value is not None:
                clauses.append(f"{clause} = ?")
                values.append(value)
        for operator, value, name in ((">=", observed_from_utc, "observed_from_utc"), ("<=", observed_to_utc, "observed_to_utc")):
            normalized = _require_utc(value, name)
            if normalized is not None:
                clauses.append(f"observed_at_utc {operator} ?")
                values.append(normalized)
        values.append(self._limit(limit))
        with self._database.connection() as connection:
            rows = connection.execute(f"SELECT * FROM market_snapshots WHERE {' AND '.join(clauses)} ORDER BY observed_at_utc ASC, id ASC LIMIT ?", values).fetchall()
        return tuple(self._snapshot(row) for row in rows)

    def get_analysis_decision(self, decision_id: str) -> AnalysisDecisionRecord:
        self._require_healthy()
        with self._database.connection() as connection:
            row = connection.execute("SELECT * FROM analysis_decisions WHERE id = ?", (decision_id,)).fetchone()
        if row is None:
            raise RecordNotFoundError(f"analysis decision not found: {decision_id}")
        return self._decision(row)

    def list_analysis_decisions(self, *, fixture_id: str | None = None, book: LedgerBook | None = None, action: DecisionAction | None = None, limit: int = 1000) -> tuple[AnalysisDecisionRecord, ...]:
        self._require_healthy()
        clauses, values = [], []
        for column, value in (("fixture_id", fixture_id), ("book", book.value if book else None), ("action", action.value if action else None)):
            if value is not None:
                clauses.append(f"{column} = ?")
                values.append(value)
        values.append(self._limit(limit))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._database.connection() as connection:
            rows = connection.execute(f"SELECT * FROM analysis_decisions {where} ORDER BY created_at_utc ASC, id ASC LIMIT ?", values).fetchall()
        return tuple(self._decision(row) for row in rows)

    def get_execution(self, execution_id: str) -> ExecutionRecord:
        self._require_healthy()
        with self._database.connection() as connection:
            row = connection.execute("SELECT * FROM executions WHERE id = ?", (execution_id,)).fetchone()
        if row is None:
            raise RecordNotFoundError(f"execution not found: {execution_id}")
        return self._execution(row)

    def list_executions(self, *, fixture_id: str | None = None, status: ExecutionStatus | None = None, limit: int = 1000) -> tuple[ExecutionRecord, ...]:
        self._require_healthy()
        clauses, values = [], []
        for column, value in (("fixture_id", fixture_id), ("status", status.value if status else None)):
            if value is not None:
                clauses.append(f"{column} = ?")
                values.append(value)
        values.append(self._limit(limit))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._database.connection() as connection:
            rows = connection.execute(f"SELECT * FROM executions {where} ORDER BY created_at_utc ASC, id ASC LIMIT ?", values).fetchall()
        return tuple(self._execution(row) for row in rows)

    def get_settlement(self, execution_id: str) -> SettlementRecord | None:
        self._require_healthy()
        with self._database.connection() as connection:
            exists = connection.execute("SELECT 1 FROM executions WHERE id = ?", (execution_id,)).fetchone()
            if exists is None:
                raise RecordNotFoundError(f"execution not found: {execution_id}")
            row = connection.execute("SELECT * FROM settlements WHERE execution_id = ?", (execution_id,)).fetchone()
        return None if row is None else self._settlement(row)

    def _list_evidence(self, table: str, mapper: Any, fixture_id: str, *, observed_before: datetime | None, provider: str | None, validation_status: str | None, limit: int, extra: tuple[tuple[str, object], ...] = ()) -> tuple[Any, ...]:
        self._require_healthy()
        self.get_fixture(fixture_id)
        clauses, values = ["fixture_id = ?"], [fixture_id]
        for column, value in (("provider", provider), ("validation_status", validation_status), *extra):
            if value is not None:
                if not isinstance(value, str) or not value:
                    raise InvalidReadFilterError(f"{column} must be a non-empty string")
                clauses.append(f"{column} = ?")
                values.append(value)
        before = _require_utc(observed_before, "observed_before")
        if before is not None:
            clauses.append("observed_at_utc <= ?")
            values.append(before)
        values.append(self._limit(limit))
        with self._database.connection() as connection:
            rows = connection.execute(f"SELECT * FROM {table} WHERE {' AND '.join(clauses)} ORDER BY observed_at_utc ASC, id ASC LIMIT ?", values).fetchall()
        return tuple(mapper(row) for row in rows)

    @staticmethod
    def _context(row: Any) -> FixtureContextRecord:
        return FixtureContextRecord(row["id"], row["fixture_id"], row["competition_name"], row["country_code"], row["season"], row["competition_round"], row["venue_name"], None if row["neutral_venue"] is None else bool(row["neutral_venue"]), row["referee_name"], row["provider"], row["source_reference"], _utc_datetime(row["observed_at_utc"]), row["validation_status"], row["raw_payload_hash"], row["mapping_version"])

    @staticmethod
    def _metric(row: Any) -> TeamMetricRecord:
        return TeamMetricRecord(row["id"], row["fixture_id"], row["team_side"], row["metric_name"], float(row["metric_value"]), row["unit"], _utc_datetime(row["period_start_utc"]), _utc_datetime(row["period_end_utc"]), row["sample_size"], row["provider"], row["source_reference"], _utc_datetime(row["observed_at_utc"]), row["validation_status"], row["raw_payload_hash"], row["mapping_version"])

    @staticmethod
    def _availability(row: Any) -> PlayerAvailabilityRecord:
        return PlayerAvailabilityRecord(row["id"], row["fixture_id"], row["team_side"], row["player_reference"], row["player_name"], row["availability_status"], row["reported_reason"], row["source_confidence"], row["provider"], row["source_reference"], _utc_datetime(row["observed_at_utc"]), row["validation_status"], row["raw_payload_hash"], row["mapping_version"])

    @staticmethod
    def _lineup(row: Any) -> LineupRecord:
        return LineupRecord(row["id"], row["fixture_id"], row["team_side"], row["player_reference"], row["player_name"], row["lineup_status"], row["position"], row["shirt_number"], row["provider"], row["source_reference"], _utc_datetime(row["observed_at_utc"]), row["validation_status"], row["raw_payload_hash"], row["mapping_version"])

    def list_fixture_context(self, fixture_id: str, *, observed_before: datetime | None = None, provider: str | None = None, validation_status: str | None = None, limit: int = 1000) -> tuple[FixtureContextRecord, ...]:
        return self._list_evidence("fixture_context_observations", self._context, fixture_id, observed_before=observed_before, provider=provider, validation_status=validation_status, limit=limit)

    def list_team_metrics(self, fixture_id: str, *, team_side: str | None = None, metric_name: str | None = None, observed_before: datetime | None = None, provider: str | None = None, validation_status: str | None = None, limit: int = 1000) -> tuple[TeamMetricRecord, ...]:
        if team_side is not None and team_side not in {"HOME", "AWAY"}:
            raise InvalidReadFilterError("team_side must be HOME or AWAY")
        return self._list_evidence("team_metric_observations", self._metric, fixture_id, observed_before=observed_before, provider=provider, validation_status=validation_status, limit=limit, extra=(("team_side", team_side), ("metric_name", metric_name)))

    def list_player_availability(self, fixture_id: str, *, team_side: str | None = None, observed_before: datetime | None = None, provider: str | None = None, validation_status: str | None = None, limit: int = 1000) -> tuple[PlayerAvailabilityRecord, ...]:
        if team_side is not None and team_side not in {"HOME", "AWAY"}:
            raise InvalidReadFilterError("team_side must be HOME or AWAY")
        return self._list_evidence("player_availability_observations", self._availability, fixture_id, observed_before=observed_before, provider=provider, validation_status=validation_status, limit=limit, extra=(("team_side", team_side),))

    def list_lineups(self, fixture_id: str, *, team_side: str | None = None, lineup_status: str | None = None, observed_before: datetime | None = None, provider: str | None = None, validation_status: str | None = None, limit: int = 1000) -> tuple[LineupRecord, ...]:
        if team_side is not None and team_side not in {"HOME", "AWAY"}:
            raise InvalidReadFilterError("team_side must be HOME or AWAY")
        if lineup_status is not None and lineup_status not in {"STARTER", "BENCH", "OUT", "UNKNOWN"}:
            raise InvalidReadFilterError("invalid lineup_status")
        return self._list_evidence("lineup_observations", self._lineup, fixture_id, observed_before=observed_before, provider=provider, validation_status=validation_status, limit=limit, extra=(("team_side", team_side), ("lineup_status", lineup_status)))
