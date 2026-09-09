"""Stable domain vocabulary shared by persistence and settlement code."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class LedgerBook(StrEnum):
    EXECUTION = "execution"
    ANALYSIS = "analysis"
    COUNTERFACTUAL = "counterfactual"


class DecisionAction(StrEnum):
    BET = "BET"
    WATCH = "WATCH"
    PASS = "PASS"


class ExecutionStatus(StrEnum):
    DRAFT = "draft"
    LOCKED = "locked"
    SETTLED = "settled"


class SettlementOutcome(StrEnum):
    WIN = "win"
    HALF_WIN = "half_win"
    PUSH = "push"
    HALF_LOSS = "half_loss"
    LOSS = "loss"


class MarketType(StrEnum):
    ASIAN_HANDICAP = "asian_handicap"
    ASIAN_TOTALS = "asian_totals"
    ASIAN_CORNERS_TOTAL = "asian_corners_total"
    THREE_WAY_CORNERS_TOTAL = "three_way_corners_total"
    TEAM_CORNERS = "team_corners"
    CORNER_HANDICAP = "corner_handicap"


Side = Literal["over", "under"]
ThreeWaySelection = Literal["over", "exactly", "under"]


@dataclass(frozen=True, slots=True)
class SettlementResult:
    outcome: SettlementOutcome
    net_pnl: float
