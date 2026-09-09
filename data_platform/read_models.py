"""Immutable public DTOs for Analysis Engine read access."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .domain import DecisionAction, ExecutionStatus, LedgerBook, SettlementOutcome


@dataclass(frozen=True, slots=True)
class FixtureRecord:
    id: str
    provider: str
    provider_fixture_id: str
    home_team: str
    away_team: str
    kickoff_at_utc: datetime
    created_at_utc: datetime


@dataclass(frozen=True, slots=True)
class MarketSnapshotRecord:
    id: str
    fixture_id: str
    provider: str
    source_reference: str
    market_type: str
    settlement_type: str
    selection: str
    line: float | None
    decimal_odds: float
    observed_at_utc: datetime
    fetched_at_utc: datetime
    raw_payload_hash: str
    validation_status: str
    mapping_version: str


@dataclass(frozen=True, slots=True)
class AnalysisDecisionRecord:
    id: str
    fixture_id: str
    book: LedgerBook
    action: DecisionAction
    market_type: str
    selection: str
    line: float | None
    odds: float | None
    rating: str
    ev: float | None
    created_at_utc: datetime
    locked_at_utc: datetime | None
    source_reference: str


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    id: str
    fixture_id: str
    market_type: str
    settlement_type: str
    selection: str
    line: float | None
    odds: float
    rating: str
    ev: float
    stake_u: float
    stake_cny: float
    source_reference: str
    created_at_utc: datetime
    locked_at_utc: datetime | None
    status: ExecutionStatus


@dataclass(frozen=True, slots=True)
class SettlementRecord:
    id: str
    execution_id: str
    outcome: SettlementOutcome
    result_payload_reference: str
    settled_at_utc: datetime
    pnl_u: float
    clv: float | None


@dataclass(frozen=True, slots=True)
class FixtureContextRecord:
    id: str
    fixture_id: str
    competition_name: str | None
    country_code: str | None
    season: str | None
    competition_round: str | None
    venue_name: str | None
    neutral_venue: bool | None
    referee_name: str | None
    provider: str
    source_reference: str
    observed_at_utc: datetime
    validation_status: str
    raw_payload_hash: str
    mapping_version: str


@dataclass(frozen=True, slots=True)
class TeamMetricRecord:
    id: str; fixture_id: str; team_side: str; metric_name: str; metric_value: float
    unit: str | None; period_start_utc: datetime | None; period_end_utc: datetime | None; sample_size: int | None
    provider: str; source_reference: str; observed_at_utc: datetime; validation_status: str; raw_payload_hash: str; mapping_version: str


@dataclass(frozen=True, slots=True)
class PlayerAvailabilityRecord:
    id: str; fixture_id: str; team_side: str; player_reference: str | None; player_name: str | None
    availability_status: str; reported_reason: str | None; source_confidence: float | None
    provider: str; source_reference: str; observed_at_utc: datetime; validation_status: str; raw_payload_hash: str; mapping_version: str


@dataclass(frozen=True, slots=True)
class LineupRecord:
    id: str; fixture_id: str; team_side: str; player_reference: str | None; player_name: str | None
    lineup_status: str; position: str | None; shirt_number: int | None
    provider: str; source_reference: str; observed_at_utc: datetime; validation_status: str; raw_payload_hash: str; mapping_version: str
