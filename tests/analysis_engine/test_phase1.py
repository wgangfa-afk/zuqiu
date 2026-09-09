from datetime import datetime, timezone

import pytest

from analysis_engine.models import MarketGroup, ModelProbability
from analysis_engine.reason_codes import ReasonCode
from analysis_engine.service import InvalidProbabilityError, MarketGroupError, Phase1AnalysisService
from data_platform.read_api import ReadRepository


def add(database, fixture, selection, odds, snapshot_id=None, market="moneyline", status="VALID"):
    return database.append_market_snapshot(fixture_id=fixture, provider="test", source_reference="synthetic://odds", market_type=market, settlement_type="normal", selection=selection, line=None, decimal_odds=odds, observed_at_utc="2026-09-08T09:00:00+00:00", raw_payload_hash=selection, validation_status=status, mapping_version="v1")


def service(database): return Phase1AnalysisService(ReadRepository(database))


def test_devig_ev_rating_watch_and_frozen_outputs(database, fixture_id):
    home, away = add(database, fixture_id, "home", 2.0), add(database, fixture_id, "away", 2.0)
    result = service(database).analyze(fixture_id=fixture_id, market_groups=(MarketGroup(fixture_id, "ml", (home, away), True, True),), model_probabilities=(ModelProbability(home, .55), ModelProbability(away, .45)), generated_at_utc=datetime(2026, 9, 8, tzinfo=timezone.utc))
    assert result.selected.action.value == "WATCH" and result.selected.rating == "B+"
    assert sum(item.devig_market_probability for item in result.ranked_candidates) == pytest.approx(1)
    assert result.selected.fair_odds == pytest.approx(1 / .55)
    assert ReasonCode.PHASE1_EXECUTION_DISABLED in result.selected.reason_codes


def test_router_scans_other_market_and_passes_unsupported(database, fixture_id):
    a, b = add(database, fixture_id, "home", 2.0), add(database, fixture_id, "away", 2.0)
    c, d = add(database, fixture_id, "yes", 2.0, market="btts"), add(database, fixture_id, "no", 2.0, market="btts")
    result = service(database).analyze(fixture_id=fixture_id, market_groups=(MarketGroup(fixture_id, "first", (a, b), True, True), MarketGroup(fixture_id, "second", (c, d), True, True)), model_probabilities=(ModelProbability(a,.5), ModelProbability(b,.5), ModelProbability(c,.6), ModelProbability(d,.4)), generated_at_utc=datetime(2026,9,8,tzinfo=timezone.utc))
    assert result.selected.snapshot_id == c


def test_invalid_probability_and_group_are_rejected(database, fixture_id):
    a, b = add(database, fixture_id, "home", 2.0), add(database, fixture_id, "away", 2.0)
    with pytest.raises(InvalidProbabilityError):
        service(database).analyze(fixture_id=fixture_id, market_groups=(MarketGroup(fixture_id,"x",(a,b),True,True),), model_probabilities=(ModelProbability(a, 1.0), ModelProbability(b,.5)), generated_at_utc=datetime(2026,9,8,tzinfo=timezone.utc))
    with pytest.raises(MarketGroupError):
        service(database).analyze(fixture_id=fixture_id, market_groups=(MarketGroup(fixture_id,"x",(a,),True,True),), model_probabilities=(ModelProbability(a,.5),), generated_at_utc=datetime(2026,9,8,tzinfo=timezone.utc))


def test_player_market_is_unpriced_pass_and_never_selected(database, fixture_id):
    a, b = add(database, fixture_id, "yes", 2.0, market="player_to_score"), add(database, fixture_id, "no", 2.0, market="player_to_score")
    result = service(database).analyze(fixture_id=fixture_id, market_groups=(MarketGroup(fixture_id, "player", (a, b), True, True),), model_probabilities=(ModelProbability(a, .6), ModelProbability(b, .4)), generated_at_utc=datetime(2026, 9, 8, tzinfo=timezone.utc))
    assert result.selected is None
    assert all(item.raw_ev is None and item.fair_odds is None and ReasonCode.UNSUPPORTED_SETTLEMENT_MODEL in item.reason_codes for item in result.ranked_candidates)


@pytest.mark.parametrize("status, code", [("STALE", ReasonCode.STALE_MARKET_DATA), ("UNMAPPED", ReasonCode.UNVERIFIED_MARKET_DATA)])
def test_hard_data_quality_rejections_never_watch_or_select(database, fixture_id, status, code):
    a, b = add(database, fixture_id, "home", 2.0, status=status), add(database, fixture_id, "away", 2.0, status=status)
    result = service(database).analyze(fixture_id=fixture_id, market_groups=(MarketGroup(fixture_id, "q", (a,b), True, True),), model_probabilities=(ModelProbability(a,.55), ModelProbability(b,.45)), generated_at_utc=datetime(2026,9,8,tzinfo=timezone.utc))
    assert result.selected is None and code in result.reason_codes
    assert ReasonCode.BELOW_WATCH_THRESHOLD not in result.reason_codes


def test_positive_edge_below_watch_threshold_has_truthful_pass_reason(database, fixture_id):
    home, away = add(database, fixture_id, "home", 2.0), add(database, fixture_id, "away", 2.0)
    result = service(database).analyze(fixture_id=fixture_id, market_groups=(MarketGroup(fixture_id, "low", (home, away), True, True),), model_probabilities=(ModelProbability(home, .505), ModelProbability(away, .495)), generated_at_utc=datetime(2026, 9, 8, tzinfo=timezone.utc))
    candidate = result.ranked_candidates[0]
    assert result.selected is None and candidate.rating == "C"
    assert candidate.risk_adjusted_ev == pytest.approx(.01)
    assert ReasonCode.BELOW_WATCH_THRESHOLD in candidate.reason_codes
    assert ReasonCode.NO_POSITIVE_EDGE not in candidate.reason_codes
    assert ReasonCode.BELOW_WATCH_THRESHOLD in result.reason_codes
    assert ReasonCode.NO_POSITIVE_EDGE not in result.reason_codes


@pytest.mark.parametrize("probability, penalty, expects_penalty", [(.5, 0.0, False), (.45, 0.0, False), (.55, .10, True), (.55, .11, True)])
def test_non_watch_edges_have_factful_reason_codes(database, fixture_id, probability, penalty, expects_penalty):
    home, away = add(database, fixture_id, "home", 2.0), add(database, fixture_id, "away", 2.0)
    result = service(database).analyze(fixture_id=fixture_id, market_groups=(MarketGroup(fixture_id, "edge", (home, away), True, True),), model_probabilities=(ModelProbability(home, probability, uncertainty_penalty=penalty), ModelProbability(away, 1-probability)), generated_at_utc=datetime(2026, 9, 8, tzinfo=timezone.utc))
    candidate = next(item for item in result.ranked_candidates if item.snapshot_id == home)
    if candidate.risk_adjusted_ev <= 0:
        assert ReasonCode.NO_POSITIVE_EDGE in candidate.reason_codes
        assert ReasonCode.BELOW_WATCH_THRESHOLD not in candidate.reason_codes
    if expects_penalty:
        assert ReasonCode.POSITIVE_RAW_EV in candidate.reason_codes
        assert ReasonCode.PENALTY_EXCEEDS_RAW_EDGE in candidate.reason_codes
        assert result.selected is None
    else:
        assert ReasonCode.PENALTY_EXCEEDS_RAW_EDGE not in candidate.reason_codes


def test_hard_rejection_and_valid_c_reasons_are_stable_tuples(database, fixture_id):
    stale_home, stale_away = add(database, fixture_id, "home", 2.0, status="STALE"), add(database, fixture_id, "away", 2.0, status="STALE")
    c_home, c_away = add(database, fixture_id, "yes", 2.0, market="btts"), add(database, fixture_id, "no", 2.0, market="btts")
    args = dict(fixture_id=fixture_id, market_groups=(MarketGroup(fixture_id, "stale", (stale_home, stale_away), True, True), MarketGroup(fixture_id, "c", (c_home, c_away), True, True)), model_probabilities=(ModelProbability(stale_home,.55), ModelProbability(stale_away,.45), ModelProbability(c_home,.505), ModelProbability(c_away,.495)), generated_at_utc=datetime(2026,9,8,tzinfo=timezone.utc))
    first, second = service(database).analyze(**args), service(database).analyze(**args)
    assert first.selected is None
    assert ReasonCode.STALE_MARKET_DATA in first.reason_codes
    assert ReasonCode.BELOW_WATCH_THRESHOLD in first.reason_codes
    assert isinstance(first.reason_codes, tuple) and len(first.reason_codes) == len(set(first.reason_codes))
    assert first.reason_codes == second.reason_codes
    assert all(isinstance(item.reason_codes, tuple) for item in first.ranked_candidates)
