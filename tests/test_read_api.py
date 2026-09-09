from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from data_platform.domain import DecisionAction, ExecutionStatus, LedgerBook, SettlementOutcome
from data_platform.read_api import DatabaseNotHealthyError, InvalidReadFilterError, ReadRepository, RecordNotFoundError
from data_platform.recovery import _rows, _table_digests, rebuild_bankroll, startup_integrity_check

from .test_ledger import execution_fields


def snapshot_fields(fixture_id, observed, **overrides):
    return {
        "fixture_id": fixture_id, "provider": "provider-a", "source_reference": "synthetic://quote",
        "market_type": "asian_total", "settlement_type": "asian", "selection": "over", "line": 2.5,
        "decimal_odds": 1.91, "observed_at_utc": observed, "raw_payload_hash": "hash",
        "validation_status": "VALID", "mapping_version": "v1", **overrides,
    }


def locked_execution(database, fixture_id):
    execution_id = database.create_execution(action=DecisionAction.BET, **execution_fields(fixture_id))
    database.lock_execution(execution_id, "2026-09-08T09:59:00+00:00")
    return execution_id


def test_fixture_mapping_and_not_found(database, fixture_id):
    repository = ReadRepository(database)
    fixture = repository.get_fixture(fixture_id)
    assert fixture.id == fixture_id and fixture.kickoff_at_utc.tzinfo is timezone.utc
    with pytest.raises(RecordNotFoundError):
        repository.get_fixture("missing")


def test_snapshot_filters_order_time_validation_and_tuple(database, fixture_id):
    database.append_market_snapshot(**snapshot_fields(fixture_id, "2026-09-08T09:01:00+00:00"))
    database.append_market_snapshot(**snapshot_fields(fixture_id, "2026-09-08T09:00:00+00:00", provider="provider-b", market_type="asian_handicap", validation_status="STALE"))
    repository = ReadRepository(database)
    snapshots = repository.list_market_snapshots(fixture_id)
    assert isinstance(snapshots, tuple)
    assert [item.observed_at_utc.minute for item in snapshots] == [0, 1]
    assert len(repository.list_market_snapshots(fixture_id, provider="provider-a", market_type="asian_total", validation_status="VALID")) == 1
    assert len(repository.list_market_snapshots(fixture_id, observed_from_utc=datetime(2026, 9, 8, 9, 1, tzinfo=timezone.utc))) == 1
    with pytest.raises(InvalidReadFilterError):
        repository.list_market_snapshots(fixture_id, observed_from_utc=datetime(2026, 9, 8, 9, 0))
    with pytest.raises(InvalidReadFilterError):
        repository.list_market_snapshots(fixture_id, observed_to_utc=datetime(2026, 9, 8, 17, 0, tzinfo=timezone(timedelta(hours=8))))


def test_decision_and_execution_records_preserve_identity_and_are_frozen(database, fixture_id):
    analysis_id = database.create_analysis_decision(book=LedgerBook.ANALYSIS, action=DecisionAction.PASS, fixture_id=fixture_id, market_type="asian_total", selection="over", rating="PASS", source_reference="synthetic://a")
    counter_id = database.create_analysis_decision(book=LedgerBook.COUNTERFACTUAL, action=DecisionAction.WATCH, fixture_id=fixture_id, market_type="cards", selection="under", rating="B", source_reference="synthetic://c")
    execution_id = locked_execution(database, fixture_id)
    repository = ReadRepository(database)
    assert repository.get_analysis_decision(analysis_id).book is LedgerBook.ANALYSIS
    assert repository.get_analysis_decision(counter_id).book is LedgerBook.COUNTERFACTUAL
    execution = repository.get_execution(execution_id)
    assert execution.status is ExecutionStatus.LOCKED and execution.stake_u == 1.0
    with pytest.raises(FrozenInstanceError):
        execution.status = ExecutionStatus.SETTLED
    assert len(repository.list_analysis_decisions(book=LedgerBook.ANALYSIS)) == 1
    assert repository.list_executions(status=ExecutionStatus.LOCKED)[0].id == execution_id


@pytest.mark.parametrize("outcome", list(SettlementOutcome))
def test_settlement_mapping_and_unsettled_behavior(database, fixture_id, outcome):
    execution_id = locked_execution(database, fixture_id)
    repository = ReadRepository(database)
    assert repository.get_settlement(execution_id) is None
    database.add_settlement(execution_id=execution_id, outcome=outcome, result_payload_reference="synthetic://ft")
    assert repository.get_settlement(execution_id).outcome is outcome


def test_missing_execution_limit_health_and_read_only_invariants(database, fixture_id):
    repository = ReadRepository(database)
    with pytest.raises(RecordNotFoundError):
        repository.get_settlement("missing")
    with pytest.raises(InvalidReadFilterError):
        repository.list_executions(limit=0)
    with database.connection() as connection:
        counts, digests = _rows(connection), _table_digests(connection)
    before = database.official_performance(), rebuild_bankroll(database)
    repository.get_fixture(fixture_id)
    repository.list_executions()
    repository.list_analysis_decisions()
    with database.connection() as connection:
        assert _rows(connection) == counts and _table_digests(connection) == digests
    assert (database.official_performance(), rebuild_bankroll(database)) == before


def test_unverified_and_recovery_required_reject_public_reads(tmp_path):
    from data_platform.database import Database

    unverified = Database(tmp_path / "unverified.sqlite3")
    unverified.initialize()
    with pytest.raises(DatabaseNotHealthyError, match="UNVERIFIED"):
        ReadRepository(unverified)
    assert startup_integrity_check(unverified).ok
    unverified.require_recovery()
    with pytest.raises(DatabaseNotHealthyError, match="RECOVERY_REQUIRED"):
        ReadRepository(unverified)
