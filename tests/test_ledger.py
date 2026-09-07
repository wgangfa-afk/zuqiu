from __future__ import annotations

import pytest

from data_platform.domain import DecisionAction, LedgerBook, SettlementOutcome


def execution_fields(fixture_id):
    return {
        "fixture_id": fixture_id,
        "market_type": "asian_handicap",
        "settlement_type": "asian",
        "selection": "home",
        "line": -0.25,
        "odds": 1.9,
        "rating": "A-",
        "ev": 0.04,
        "stake_u": 1.0,
        "stake_cny": 100.0,
        "source_reference": "synthetic://verified-entry-price",
    }


def test_execution_lock_makes_pre_match_fields_immutable(database, fixture_id):
    execution_id = database.create_execution(action=DecisionAction.BET, **execution_fields(fixture_id))
    database.lock_execution(execution_id, "2026-09-08T09:00:00+00:00")
    with pytest.raises(ValueError, match="immutable"):
        database.update_execution_draft(execution_id, odds=2.1)
    with database.connection() as connection:
        with pytest.raises(Exception, match="immutable"):
            connection.execute("UPDATE executions SET odds = 2.1 WHERE id = ?", (execution_id,))


@pytest.mark.parametrize("action", [DecisionAction.PASS, DecisionAction.WATCH])
def test_pass_and_watch_cannot_be_promoted_to_execution(database, fixture_id, action):
    decision_id = database.create_analysis_decision(
        book=LedgerBook.ANALYSIS,
        action=action,
        fixture_id=fixture_id,
        market_type="asian_total",
        selection="over",
        rating="B+",
        source_reference="synthetic://analysis",
    )
    assert decision_id
    with pytest.raises(ValueError, match="explicit pre-match BET"):
        database.create_execution(action=action, **execution_fields(fixture_id))


def test_analysis_and_counterfactual_do_not_enter_official_roi(database, fixture_id):
    for book in (LedgerBook.ANALYSIS, LedgerBook.COUNTERFACTUAL):
        database.create_analysis_decision(
            book=book,
            action=DecisionAction.PASS,
            fixture_id=fixture_id,
            market_type="three_way_corners_total",
            selection="over",
            rating="PASS",
            source_reference="synthetic://counterfactual",
        )
    assert database.official_performance() == {"pnl_u": 0.0, "stake_u": 0.0, "roi": 0.0}


def test_execution_pnl_and_roi_only_use_settled_execution(database, fixture_id):
    execution_id = database.create_execution(action=DecisionAction.BET, **execution_fields(fixture_id))
    database.lock_execution(execution_id)
    database.add_settlement(execution_id=execution_id, outcome=SettlementOutcome.HALF_WIN, result_payload_reference="synthetic://ft-result")
    assert database.official_performance() == {"pnl_u": 0.45, "stake_u": 1.0, "roi": 0.45}
