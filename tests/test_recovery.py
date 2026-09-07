from __future__ import annotations

import sqlite3

import pytest

from data_platform.domain import DecisionAction, SettlementOutcome
from data_platform.recovery import create_backup, rebuild_bankroll, restore_backup, startup_integrity_check

from .test_ledger import execution_fields


def locked_execution(database, fixture_id):
    execution_id = database.create_execution(action=DecisionAction.BET, **execution_fields(fixture_id))
    database.lock_execution(execution_id, "2026-09-08T09:59:00+00:00")
    return execution_id


def test_backup_manifest_and_restore_to_new_database(database, fixture_id, tmp_path):
    execution_id = locked_execution(database, fixture_id)
    database.add_settlement(execution_id=execution_id, outcome=SettlementOutcome.WIN, result_payload_reference="synthetic://ft")
    manifest = create_backup(database, tmp_path / "backup" , git_commit_sha="test")
    restored = restore_backup(manifest, tmp_path / "restored.sqlite3")
    assert startup_integrity_check(restored).ok
    assert rebuild_bankroll(restored) == {"balance_u": -0.1, "rebuilt_balance_u": -0.1}


def test_settlement_is_idempotent_without_duplicate_ledger(database, fixture_id):
    execution_id = locked_execution(database, fixture_id)
    first = database.add_settlement(execution_id=execution_id, outcome=SettlementOutcome.WIN, result_payload_reference="synthetic://ft")
    assert database.add_settlement(execution_id=execution_id, outcome=SettlementOutcome.WIN, result_payload_reference="synthetic://ft") == first
    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM bankroll_ledger WHERE execution_id=?", (execution_id,)).fetchone()[0] == 2
    with pytest.raises(ValueError, match="Conflicting"):
        database.add_settlement(execution_id=execution_id, outcome=SettlementOutcome.LOSS, result_payload_reference="synthetic://changed")


def test_integrity_failure_enters_recovery_required(database, fixture_id):
    execution_id = locked_execution(database, fixture_id)
    with database.connection() as connection:
        connection.execute("DELETE FROM bankroll_ledger WHERE execution_id = ?", (execution_id,))
    report = startup_integrity_check(database)
    assert not report.ok
    with pytest.raises(RuntimeError, match="RECOVERY_REQUIRED"):
        database.create_execution(action=DecisionAction.BET, **execution_fields(fixture_id))


def test_backup_checksum_mismatch_is_rejected(database, tmp_path):
    manifest = create_backup(database, tmp_path / "backup")
    backup_path = next((tmp_path / "backup").glob("*.sqlite3"))
    with backup_path.open("ab") as file:
        file.write(b"tamper")
    with pytest.raises(ValueError, match="checksum"):
        restore_backup(manifest, tmp_path / "restored.sqlite3")


def test_crash_before_settlement_leaves_locked_execution_consistent(database, fixture_id):
    locked_execution(database, fixture_id)
    assert startup_integrity_check(database).ok


def test_crash_after_settlement_is_transactionally_consistent(database, fixture_id):
    execution_id = locked_execution(database, fixture_id)
    database.add_settlement(execution_id=execution_id, outcome=SettlementOutcome.PUSH, result_payload_reference="synthetic://ft")
    assert startup_integrity_check(database).ok
