"""Pure Phase 1 pricing and routing over B's typed read contract."""
from __future__ import annotations

import math
from datetime import datetime, timezone

from data_platform.domain import DecisionAction
from data_platform.read_api import ReadRepository
from data_platform.read_models import MarketSnapshotRecord

from .models import MarketGroup, ModelProbability, PricedSelection, RoutingDecision
from .reason_codes import ReasonCode


class AnalysisInputError(ValueError): pass
class InvalidProbabilityError(AnalysisInputError): pass
class InvalidOddsError(AnalysisInputError): pass
class MarketGroupError(AnalysisInputError): pass
class UnsupportedSettlementModelError(AnalysisInputError): pass


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise InvalidProbabilityError(f"{label} must be a finite non-bool number")
    return float(value)


def _utc(value: datetime) -> None:
    if value.tzinfo is not timezone.utc:
        raise AnalysisInputError("generated_at_utc must be UTC timezone-aware")


def _unsupported(snapshot: MarketSnapshotRecord) -> bool:
    kind = snapshot.settlement_type.lower()
    market = snapshot.market_type.lower()
    return "asian" in kind or "asian" in market or "corner" in market or "push" in kind or "card" in market


class Phase1AnalysisService:
    def __init__(self, repository: ReadRepository) -> None: self._repository = repository

    def analyze(self, *, fixture_id: str, market_groups: tuple[MarketGroup, ...], model_probabilities: tuple[ModelProbability, ...], generated_at_utc: datetime) -> RoutingDecision:
        _utc(generated_at_utc)
        self._repository.get_fixture(fixture_id)
        snapshots_by_id = {item.id: item for item in self._repository.list_market_snapshots(fixture_id, limit=5000)}
        probability_by_id: dict[str, ModelProbability] = {}
        for model in model_probabilities:
            if model.snapshot_id in probability_by_id: raise AnalysisInputError("duplicate model probability")
            probability_by_id[model.snapshot_id] = model
            probability = _finite(model.probability, "probability")
            if not 0 < probability < 1: raise InvalidProbabilityError("probability must be between 0 and 1")
            for penalty in (model.uncertainty_penalty, model.data_quality_penalty, model.correlation_penalty):
                value = _finite(penalty, "penalty")
                if not 0 <= value <= 1: raise InvalidProbabilityError("penalty must be between 0 and 1")
        candidates: list[PricedSelection] = []
        expected_ids: set[str] = set()
        for group in market_groups:
            if group.fixture_id != fixture_id: raise MarketGroupError("mixed fixture group")
            if not group.exhaustive or not group.mutually_exclusive: raise MarketGroupError("market group must be exhaustive and mutually exclusive")
            if len(group.snapshot_ids) not in (2, 3): raise MarketGroupError("market group must contain two or three selections")
            if len(set(group.snapshot_ids)) != len(group.snapshot_ids): raise MarketGroupError("duplicate snapshot id")
            expected_ids.update(group.snapshot_ids)
            try:
                snapshots = tuple(snapshots_by_id[snapshot_id] for snapshot_id in group.snapshot_ids)
            except KeyError as error:
                raise MarketGroupError(f"snapshot is not available for fixture: {error.args[0]}") from error
            self._validate_group(group, snapshots)
            missing = [snapshot.id for snapshot in snapshots if snapshot.id not in probability_by_id]
            if missing: raise AnalysisInputError("missing model probability")
            candidates.extend(self._price_group(group, snapshots, probability_by_id))
        if set(probability_by_id) != expected_ids: raise AnalysisInputError("extra model probability")
        ranked = tuple(sorted(candidates, key=lambda item: (-item.risk_adjusted_ev, -item.raw_ev, item.observed_at_utc.timestamp() * -1, item.snapshot_id)))
        selectable = next((item for item in ranked if item.rating in {"B+", "B"} and item.action is DecisionAction.WATCH), None)
        if selectable is None:
            return RoutingDecision(fixture_id, None, ranked, DecisionAction.PASS, "PASS", (ReasonCode.NO_POSITIVE_EDGE,), generated_at_utc)
        reasons = tuple(dict.fromkeys((*selectable.reason_codes, ReasonCode.BEST_CROSS_MARKET_VALUE)))
        return RoutingDecision(fixture_id, selectable, ranked, DecisionAction.WATCH, selectable.rating, reasons, generated_at_utc)

    def _validate_group(self, group: MarketGroup, snapshots: tuple[MarketSnapshotRecord, ...]) -> None:
        if any(item.fixture_id != group.fixture_id for item in snapshots): raise MarketGroupError("mixed fixture group")
        if len({item.market_type for item in snapshots}) != 1 or len({item.settlement_type for item in snapshots}) != 1: raise MarketGroupError("mixed market group")
        if len({item.line for item in snapshots}) != 1: raise MarketGroupError("mixed line group")
        if len({item.observed_at_utc for item in snapshots}) != 1: raise MarketGroupError("mixed observation time group")
        for snapshot in snapshots:
            odds = _finite(snapshot.decimal_odds, "odds")
            if odds <= 1: raise InvalidOddsError("decimal odds must exceed 1")

    def _price_group(self, group: MarketGroup, snapshots: tuple[MarketSnapshotRecord, ...], models: dict[str, ModelProbability]) -> tuple[PricedSelection, ...]:
        implied = tuple(1 / float(snapshot.decimal_odds) for snapshot in snapshots)
        overround = sum(implied)
        if overround <= 0: raise InvalidOddsError("overround must be positive")
        devig = tuple(value / overround for value in implied)
        if abs(sum(devig) - 1) > 1e-9: raise AnalysisInputError("de-vig probability sum mismatch")
        output = []
        for snapshot, implied_probability, devig_probability in zip(snapshots, implied, devig):
            model = models[snapshot.id]
            raw_ev = model.probability * snapshot.decimal_odds - 1
            adjusted = raw_ev - model.uncertainty_penalty - model.data_quality_penalty - model.correlation_penalty
            reasons: list[ReasonCode] = []
            if _unsupported(snapshot): reasons.append(ReasonCode.UNSUPPORTED_SETTLEMENT_MODEL)
            if snapshot.validation_status == "STALE": reasons.append(ReasonCode.STALE_MARKET_DATA)
            elif snapshot.validation_status != "VALID": reasons.append(ReasonCode.UNVERIFIED_MARKET_DATA)
            if raw_ev > 0: reasons.append(ReasonCode.POSITIVE_RAW_EV)
            if adjusted > 0: reasons.append(ReasonCode.POSITIVE_RISK_ADJUSTED_EV)
            if adjusted <= 0: reasons.extend((ReasonCode.NO_POSITIVE_EDGE, ReasonCode.PENALTY_EXCEEDS_RAW_EDGE))
            hard = bool({ReasonCode.UNSUPPORTED_SETTLEMENT_MODEL, ReasonCode.STALE_MARKET_DATA, ReasonCode.UNVERIFIED_MARKET_DATA}.intersection(reasons))
            rating = "B+" if adjusted >= .04 and snapshot.validation_status == "VALID" and not hard else "B" if adjusted >= .02 and not hard else "C" if adjusted > 0 and not hard else "PASS"
            action = DecisionAction.WATCH if rating in {"B+", "B"} else DecisionAction.PASS
            if action is DecisionAction.WATCH: reasons.extend((ReasonCode.PHASE1_RATING_CAP, ReasonCode.PHASE1_EXECUTION_DISABLED))
            output.append(PricedSelection(snapshot.fixture_id, snapshot.id, group.market_key, snapshot.market_type, snapshot.settlement_type, snapshot.selection, snapshot.line, snapshot.decimal_odds, implied_probability, devig_probability, model.probability, 1 / model.probability, raw_ev, model.uncertainty_penalty, model.data_quality_penalty, model.correlation_penalty, adjusted, rating, action, tuple(dict.fromkeys(reasons)), snapshot.source_reference, snapshot.observed_at_utc))
        return tuple(output)
