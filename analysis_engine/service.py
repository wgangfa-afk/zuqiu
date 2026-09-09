"""Pure Phase 1 pricing and routing over B's typed read contract."""
from __future__ import annotations

from datetime import datetime, timezone

from data_platform.domain import DecisionAction
from data_platform.read_api import ReadRepository
from data_platform.read_models import MarketSnapshotRecord

from .models import MarketGroup, ModelProbability, PricedSelection, RoutingDecision
from .exceptions import AnalysisInputError, InvalidOddsError, InvalidProbabilityError, MarketGroupError, UnsupportedSettlementModelError
from .ev import calculate
from .pricing import devig, supports_binary_market, valid_odds, valid_probability
from .rating import rate
from .reason_codes import ReasonCode


def _utc(value: datetime) -> None:
    if value.tzinfo is not timezone.utc:
        raise AnalysisInputError("generated_at_utc must be UTC timezone-aware")


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
            probability = valid_probability(model.probability)
            for penalty in (model.uncertainty_penalty, model.data_quality_penalty, model.correlation_penalty):
                valid_probability(penalty, penalty=True)
        candidates: list[PricedSelection] = []
        expected_ids: set[str] = set(); keys: set[str] = set()
        for group in market_groups:
            if group.fixture_id != fixture_id or not group.market_key.strip() or group.market_key in keys: raise MarketGroupError("invalid or duplicate market key")
            keys.add(group.market_key)
            if type(group.exhaustive) is not bool or type(group.mutually_exclusive) is not bool or not group.exhaustive or not group.mutually_exclusive: raise MarketGroupError("market group must be exhaustive and mutually exclusive booleans")
            if len(group.snapshot_ids) not in (2, 3): raise MarketGroupError("market group must contain two or three selections")
            if len(set(group.snapshot_ids)) != len(group.snapshot_ids): raise MarketGroupError("duplicate snapshot id")
            if expected_ids.intersection(group.snapshot_ids): raise MarketGroupError("snapshot appears in multiple groups")
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
        def quality(item: PricedSelection) -> int:
            return 0 if item.validation_status == "VALID" else 1 if item.validation_status == "STALE" else 2
        def numeric(value: float | None) -> float:
            return value if value is not None else float("-inf")
        ranked = tuple(sorted(candidates, key=lambda item: (item.risk_adjusted_ev is None, -numeric(item.risk_adjusted_ev), -numeric(item.raw_ev), quality(item), -item.observed_at_utc.timestamp(), item.snapshot_id)))
        hard = {ReasonCode.UNSUPPORTED_SETTLEMENT_MODEL, ReasonCode.STALE_MARKET_DATA, ReasonCode.UNVERIFIED_MARKET_DATA}
        selectable = next((item for item in ranked if item.rating in {"B+", "B"} and item.action is DecisionAction.WATCH and item.risk_adjusted_ev is not None and not hard.intersection(item.reason_codes)), None)
        if selectable is None:
            rejected = tuple(dict.fromkeys(code for item in ranked for code in item.reason_codes if code in hard))
            below = any(item.risk_adjusted_ev is not None and item.risk_adjusted_ev > 0 for item in ranked)
            reasons = list(rejected)
            if below:
                reasons.extend((ReasonCode.BELOW_WATCH_THRESHOLD, ReasonCode.PHASE1_EXECUTION_DISABLED))
            if not reasons:
                reasons.append(ReasonCode.NO_POSITIVE_EDGE)
            return RoutingDecision(fixture_id, None, ranked, DecisionAction.PASS, "PASS", tuple(dict.fromkeys(reasons)), generated_at_utc)
        reasons = tuple(dict.fromkeys((*selectable.reason_codes, ReasonCode.BEST_CROSS_MARKET_VALUE)))
        return RoutingDecision(fixture_id, selectable, ranked, DecisionAction.WATCH, selectable.rating, reasons, generated_at_utc)

    def _validate_group(self, group: MarketGroup, snapshots: tuple[MarketSnapshotRecord, ...]) -> None:
        if any(item.fixture_id != group.fixture_id for item in snapshots): raise MarketGroupError("mixed fixture group")
        if len({item.market_type for item in snapshots}) != 1 or len({item.settlement_type for item in snapshots}) != 1: raise MarketGroupError("mixed market group")
        if len({item.line for item in snapshots}) != 1: raise MarketGroupError("mixed line group")
        if len({item.observed_at_utc for item in snapshots}) != 1: raise MarketGroupError("mixed observation time group")
        if len({item.selection for item in snapshots}) != len(snapshots): raise MarketGroupError("duplicate selection")
        market = snapshots[0].market_type.lower()
        selections = {item.selection.lower() for item in snapshots}
        expected = {"1x2": (3, {"home", "draw", "away"}), "moneyline": (2, None), "btts": (2, {"yes", "no"})}
        if market in expected:
            count, required = expected[market]
            if len(snapshots) != count or (required is not None and selections != required):
                raise MarketGroupError("invalid supported market selections")
        for snapshot in snapshots: valid_odds(snapshot.decimal_odds)

    def _price_group(self, group: MarketGroup, snapshots: tuple[MarketSnapshotRecord, ...], models: dict[str, ModelProbability]) -> tuple[PricedSelection, ...]:
        supported = supports_binary_market(snapshots[0].market_type, snapshots[0].settlement_type)
        devig_probabilities = devig(tuple(snapshot.decimal_odds for snapshot in snapshots)) if supported else (None,) * len(snapshots)
        implied = tuple(1 / float(snapshot.decimal_odds) for snapshot in snapshots) if supported else (None,) * len(snapshots)
        if abs(sum(models[item.id].probability for item in snapshots) - 1) > 1e-9: raise InvalidProbabilityError("group model probabilities must sum to one")
        output = []
        for snapshot, implied_probability, devig_probability in zip(snapshots, implied, devig_probabilities):
            model = models[snapshot.id]
            reasons: list[ReasonCode] = []
            if not supported:
                reasons.extend((ReasonCode.UNSUPPORTED_SETTLEMENT_MODEL, ReasonCode.PHASE1_EXECUTION_DISABLED))
                output.append(PricedSelection(snapshot.fixture_id, snapshot.id, group.market_key, snapshot.market_type, snapshot.settlement_type, snapshot.validation_status, snapshot.selection, snapshot.line, snapshot.decimal_odds, None, None, model.probability, None, None, model.uncertainty_penalty, model.data_quality_penalty, model.correlation_penalty, None, "PASS", DecisionAction.PASS, tuple(reasons), snapshot.source_reference, snapshot.observed_at_utc))
                continue
            fair_odds, raw_ev, adjusted = calculate(model.probability, snapshot.decimal_odds, (model.uncertainty_penalty, model.data_quality_penalty, model.correlation_penalty))
            if snapshot.validation_status == "STALE": reasons.append(ReasonCode.STALE_MARKET_DATA)
            elif snapshot.validation_status != "VALID": reasons.append(ReasonCode.UNVERIFIED_MARKET_DATA)
            if raw_ev > 0: reasons.append(ReasonCode.POSITIVE_RAW_EV)
            if adjusted > 0: reasons.append(ReasonCode.POSITIVE_RISK_ADJUSTED_EV)
            if adjusted <= 0:
                reasons.append(ReasonCode.NO_POSITIVE_EDGE)
                if raw_ev > 0:
                    reasons.append(ReasonCode.PENALTY_EXCEEDS_RAW_EDGE)
            hard = bool({ReasonCode.UNSUPPORTED_SETTLEMENT_MODEL, ReasonCode.STALE_MARKET_DATA, ReasonCode.UNVERIFIED_MARKET_DATA}.intersection(reasons))
            rating, action = rate(adjusted, snapshot.validation_status == "VALID" and not hard)
            if action is DecisionAction.WATCH: reasons.extend((ReasonCode.PHASE1_RATING_CAP, ReasonCode.PHASE1_EXECUTION_DISABLED))
            elif rating == "C": reasons.extend((ReasonCode.BELOW_WATCH_THRESHOLD, ReasonCode.PHASE1_EXECUTION_DISABLED))
            output.append(PricedSelection(snapshot.fixture_id, snapshot.id, group.market_key, snapshot.market_type, snapshot.settlement_type, snapshot.validation_status, snapshot.selection, snapshot.line, snapshot.decimal_odds, implied_probability, devig_probability, model.probability, fair_odds, raw_ev, model.uncertainty_penalty, model.data_quality_penalty, model.correlation_penalty, adjusted, rating, action, tuple(dict.fromkeys(reasons)), snapshot.source_reference, snapshot.observed_at_utc))
        return tuple(output)
