from __future__ import annotations

import sqlite3
from uuid import uuid4

import pytest

from data_platform.database import Database
from data_platform.recovery import startup_integrity_check
from data_platform.domain import DecisionAction, LedgerBook, SettlementOutcome

from .test_ledger import execution_fields


def ledger_entries(database, execution_id):
    with database.connection() as connection:
        return connection.execute(
            "SELECT entry_type, amount_u FROM bankroll_ledger WHERE execution_id = ? ORDER BY entry_type",
            (execution_id,),
        ).fetchall()


def test_draft_does_not_affect_bankroll_and_lock_records_one_stake(database, fixture_id):
    execution_id = database.create_execution(action=DecisionAction.BET, **execution_fields(fixture_id))
    assert ledger_entries(database, execution_id) == []
    database.update_execution_draft(execution_id, stake_u=1.5, stake_cny=150.0)
    database.lock_execution(execution_id, "2026-09-08T09:59:00+00:00")
    entries = ledger_entries(database, execution_id)
    assert [(entry["entry_type"], entry["amount_u"]) for entry in entries] == [("stake", -1.5)]
    with pytest.raises(ValueError, match="already locked"):
        database.lock_execution(execution_id, "2026-09-08T09:59:30+00:00")
    assert len(ledger_entries(database, execution_id)) == 1


def test_execution_cannot_be_created_or_locked_at_or_after_kickoff(tmp_path):
    now = ["2026-09-08T09:59:00+00:00"]
    database = Database(tmp_path / "kickoff.sqlite3", clock=lambda: now[0])
    database.initialize()
    assert startup_integrity_check(database).ok
    fixture_id = database.create_fixture(
        provider="synthetic", provider_fixture_id="kickoff", home_team="Home", away_team="Away",
        kickoff_at_utc="2026-09-08T10:00:00+00:00",
    )
    execution_id = database.create_execution(action=DecisionAction.BET, **execution_fields(fixture_id))
    database.lock_execution(execution_id)

    draft_id = database.create_execution(action=DecisionAction.BET, **execution_fields(fixture_id))
    now[0] = "2026-09-08T10:00:00+00:00"
    with pytest.raises(ValueError, match="before fixture kickoff"):
        database.lock_execution(draft_id)
    with pytest.raises(ValueError, match="before fixture kickoff"):
        database.create_execution(action=DecisionAction.BET, **execution_fields(fixture_id))

    now[0] = "2026-09-08T10:01:00+00:00"
    with pytest.raises(ValueError, match="before fixture kickoff"):
        database.create_execution(action=DecisionAction.BET, **execution_fields(fixture_id))


def test_post_kickoff_pass_or_watch_cannot_be_backfilled_as_bet(tmp_path):
    now = ["2026-09-08T09:59:00+00:00"]
    database = Database(tmp_path / "backfill.sqlite3", clock=lambda: now[0])
    database.initialize()
    assert startup_integrity_check(database).ok
    fixture_id = database.create_fixture(
        provider="synthetic", provider_fixture_id="backfill", home_team="Home", away_team="Away",
        kickoff_at_utc="2026-09-08T10:00:00+00:00",
    )
    for action in (DecisionAction.PASS, DecisionAction.WATCH):
        database.create_analysis_decision(
            book=LedgerBook.ANALYSIS, action=action, fixture_id=fixture_id, market_type="asian_total",
            selection="over", rating="B+", source_reference="synthetic://pre-kickoff-decision",
        )
    now[0] = "2026-09-08T10:01:00+00:00"
    with pytest.raises(ValueError, match="before fixture kickoff"):
        database.create_execution(action=DecisionAction.BET, **execution_fields(fixture_id))


@pytest.mark.parametrize(
    ("outcome", "expected_pnl"),
    [
        (SettlementOutcome.WIN, 0.90),
        (SettlementOutcome.HALF_WIN, 0.45),
        (SettlementOutcome.PUSH, 0.0),
        (SettlementOutcome.HALF_LOSS, -0.50),
        (SettlementOutcome.LOSS, -1.0),
    ],
)
def test_settlement_pnl_is_calculated_from_locked_execution(database, fixture_id, outcome, expected_pnl):
    execution_id = database.create_execution(action=DecisionAction.BET, **execution_fields(fixture_id))
    database.lock_execution(execution_id, "2026-09-08T09:59:00+00:00")
    database.add_settlement(execution_id=execution_id, outcome=outcome, result_payload_reference="synthetic://ft")
    with database.connection() as connection:
        stored = connection.execute("SELECT pnl_u FROM settlements WHERE execution_id = ?", (execution_id,)).fetchone()
    assert stored["pnl_u"] == pytest.approx(expected_pnl)


def test_incorrect_manually_supplied_pnl_is_rejected(database, fixture_id):
    execution_id = database.create_execution(action=DecisionAction.BET, **execution_fields(fixture_id))
    database.lock_execution(execution_id, "2026-09-08T09:59:00+00:00")
    with pytest.raises(ValueError, match="system-calculated"):
        database.add_settlement(
            execution_id=execution_id, outcome=SettlementOutcome.WIN,
            result_payload_reference="synthetic://ft", expected_pnl_u=999.0,
        )
    assert [(entry["entry_type"], entry["amount_u"]) for entry in ledger_entries(database, execution_id)] == [("stake", -1.0)]


def test_market_snapshots_cannot_be_updated_or_deleted(database, fixture_id):
    snapshot_id = database.append_market_snapshot(
        fixture_id=fixture_id, provider="synthetic", source_reference="synthetic://snapshot",
        market_type="asian_total", settlement_type="asian", selection="over", line=2.5,
        decimal_odds=1.9, observed_at_utc="2026-09-08T09:00:00+00:00",
        raw_payload_hash="test-hash", validation_status="VALID", mapping_version="v1",
    )
    with database.connection() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("UPDATE market_snapshots SET decimal_odds = 2.0 WHERE id = ?", (snapshot_id,))
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM market_snapshots WHERE id = ?", (snapshot_id,))


def test_settlement_and_bankroll_are_append_only(database, fixture_id):
    execution_id = database.create_execution(action=DecisionAction.BET, **execution_fields(fixture_id))
    database.lock_execution(execution_id, "2026-09-08T09:59:00+00:00")
    database.add_settlement(execution_id=execution_id, outcome=SettlementOutcome.WIN, result_payload_reference="synthetic://ft")
    with database.connection() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("UPDATE settlements SET clv=9 WHERE execution_id=?", (execution_id,))
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM bankroll_ledger WHERE execution_id=?", (execution_id,))


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("fixture_id", "not-the-original-fixture"), ("market_type", "asian_total"),
        ("settlement_type", "three_way"), ("selection", "away"), ("line", 0.5),
        ("odds", 2.0), ("rating", "S"), ("ev", 0.9), ("stake_u", 2.0),
        ("stake_cny", 200.0), ("source_reference", "synthetic://changed"),
        ("created_at_utc", "2026-09-08T09:58:00+00:00"),
        ("locked_at_utc", "2026-09-08T09:58:30+00:00"),
    ],
)
def test_all_locked_execution_core_fields_resist_direct_sql_changes(database, fixture_id, column, value):
    execution_id = database.create_execution(action=DecisionAction.BET, **execution_fields(fixture_id))
    database.lock_execution(execution_id, "2026-09-08T09:59:00+00:00")
    with database.connection() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(f"UPDATE executions SET {column} = ? WHERE id = ?", (value, execution_id))


def test_execution_status_cannot_move_backward(database, fixture_id):
    execution_id = database.create_execution(action=DecisionAction.BET, **execution_fields(fixture_id))
    database.lock_execution(execution_id, "2026-09-08T09:59:00+00:00")
    with database.connection() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="transition"):
            connection.execute("UPDATE executions SET status = 'draft' WHERE id = ?", (execution_id,))
    database.add_settlement(execution_id=execution_id, outcome=SettlementOutcome.PUSH, result_payload_reference="synthetic://ft")
    with database.connection() as connection:
        for invalid_status in ("locked", "draft"):
            with pytest.raises(sqlite3.IntegrityError, match="transition"):
                connection.execute("UPDATE executions SET status = ? WHERE id = ?", (invalid_status, execution_id))


def test_every_connection_enforces_foreign_keys(database):
    with database.connection() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO executions VALUES (?, ?, 'asian_total', 'asian', 'over', 2.5, 1.9, 'A', 0.1, 1, 100, 'synthetic://x', '2026-09-08T09:00:00+00:00', NULL, 'draft')",
                ("orphan", "missing-fixture"),
            )


def test_initialize_refreshes_existing_trigger_definitions(database, fixture_id):
    with database.connection() as connection:
        connection.execute("DROP TRIGGER locked_execution_is_immutable")
        connection.execute("CREATE TRIGGER locked_execution_is_immutable BEFORE UPDATE ON executions WHEN OLD.locked_at_utc IS NOT NULL BEGIN SELECT RAISE(ABORT, 'old trigger'); END")
    database.initialize()
    execution_id = database.create_execution(action=DecisionAction.BET, **execution_fields(fixture_id))
    database.lock_execution(execution_id, "2026-09-08T09:59:00+00:00")
    with database.connection() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("UPDATE executions SET stake_cny = 200 WHERE id = ?", (execution_id,))


def test_analysis_execution_counterfactual_review_books_cannot_cross(database, fixture_id):
    decision_id = database.create_analysis_decision(
        book=LedgerBook.ANALYSIS, action=DecisionAction.PASS, fixture_id=fixture_id,
        market_type="asian_total", selection="under", rating="PASS",
        source_reference="synthetic://analysis",
    )
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO review_records VALUES (?, 'counterfactual', NULL, ?, NULL, ?, 'crossed book')",
            (str(uuid4()), decision_id, "2026-09-08T12:00:00+00:00"),
        )
    report = startup_integrity_check(database)
    assert not report.ok
    assert any("crosses book boundary" in error for error in report.errors)
