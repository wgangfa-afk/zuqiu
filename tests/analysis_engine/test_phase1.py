from datetime import datetime, timezone

import pytest

from analysis_engine.models import MarketGroup, ModelProbability
from analysis_engine.reason_codes import ReasonCode
from analysis_engine.service import InvalidProbabilityError, MarketGroupError, Phase1AnalysisService
from data_platform.read_api import ReadRepository


def add(database, fixture, selection, odds, snapshot_id=None, market="1x2"):
    return database.append_market_snapshot(fixture_id=fixture, provider="test", source_reference="synthetic://odds", market_type=market, settlement_type="normal", selection=selection, line=None, decimal_odds=odds, observed_at_utc="2026-09-08T09:00:00+00:00", raw_payload_hash=selection, validation_status="VALID", mapping_version="v1")


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
    result = service(database).analyze(fixture_id=fixture_id, market_groups=(MarketGroup(fixture_id, "first", (a, b), True, True), MarketGroup(fixture_id, "second", (c, d), True, True)), model_probabilities=(ModelProbability(a,.4), ModelProbability(b,.4), ModelProbability(c,.6), ModelProbability(d,.4)), generated_at_utc=datetime(2026,9,8,tzinfo=timezone.utc))
    assert result.selected.snapshot_id == c


def test_invalid_probability_and_group_are_rejected(database, fixture_id):
    a, b = add(database, fixture_id, "home", 2.0), add(database, fixture_id, "away", 2.0)
    with pytest.raises(InvalidProbabilityError):
        service(database).analyze(fixture_id=fixture_id, market_groups=(MarketGroup(fixture_id,"x",(a,b),True,True),), model_probabilities=(ModelProbability(a, 1.0), ModelProbability(b,.5)), generated_at_utc=datetime(2026,9,8,tzinfo=timezone.utc))
    with pytest.raises(MarketGroupError):
        service(database).analyze(fixture_id=fixture_id, market_groups=(MarketGroup(fixture_id,"x",(a,),True,True),), model_probabilities=(ModelProbability(a,.5),), generated_at_utc=datetime(2026,9,8,tzinfo=timezone.utc))
