from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from data_platform.domain import DecisionAction

from .reason_codes import ReasonCode


@dataclass(frozen=True, slots=True)
class ModelProbability:
    snapshot_id: str
    probability: float
    uncertainty_penalty: float = 0.0
    data_quality_penalty: float = 0.0
    correlation_penalty: float = 0.0


@dataclass(frozen=True, slots=True)
class MarketGroup:
    fixture_id: str
    market_key: str
    snapshot_ids: tuple[str, ...]
    exhaustive: bool
    mutually_exclusive: bool


@dataclass(frozen=True, slots=True)
class PricedSelection:
    fixture_id: str; snapshot_id: str; market_key: str; market_type: str; settlement_type: str
    selection: str; line: float | None; market_odds: float; market_implied_probability: float
    devig_market_probability: float; model_probability: float; fair_odds: float; raw_ev: float
    uncertainty_penalty: float; data_quality_penalty: float; correlation_penalty: float
    risk_adjusted_ev: float; rating: str; action: DecisionAction; reason_codes: tuple[ReasonCode, ...]
    source_reference: str; observed_at_utc: datetime


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    fixture_id: str
    selected: PricedSelection | None
    ranked_candidates: tuple[PricedSelection, ...]
    action: DecisionAction
    rating: str
    reason_codes: tuple[ReasonCode, ...]
    generated_at_utc: datetime
