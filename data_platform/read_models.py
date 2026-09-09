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
