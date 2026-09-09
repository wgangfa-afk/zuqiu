from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from data_platform import IdempotencyConflictError
from data_platform.read_api import DatabaseNotHealthyError, InvalidReadFilterError, ReadRepository, RecordNotFoundError
from data_platform.recovery import _rows, _table_digests, create_backup, restore_backup


def common(fixture_id, **extra):
    return {
        "fixture_id": fixture_id, "provider": "provider-a", "source_reference": "source://fact",
        "observed_at_utc": "2026-09-08T09:00:00+00:00", "validation_status": "VALID",
        "raw_payload_hash": "payload-a", "mapping_version": "v1", **extra,
    }


def seed(database, fixture_id):
    database.append_fixture_context(**common(fixture_id, competition_name="League", neutral_venue=False))
    database.append_team_metric(**common(fixture_id, team_side="HOME", metric_name="corners", metric_value=4.0, unit="count", sample_size=3))
    database.append_player_availability(**common(fixture_id, team_side="AWAY", player_reference="p1", player_name="Player", availability_status="OUT"))
    database.append_lineup(**common(fixture_id, team_side="HOME", player_reference="p2", player_name="Starter", lineup_status="STARTER", shirt_number=9))


def test_all_evidence_types_are_append_only_typed_and_readable(database, fixture_id):
    seed(database, fixture_id)
    repository = ReadRepository(database)
    context = repository.list_fixture_context(fixture_id)
    metrics = repository.list_team_metrics(fixture_id)
    availability = repository.list_player_availability(fixture_id)
    lineups = repository.list_lineups(fixture_id)
    assert all(isinstance(value, tuple) for value in (context, metrics, availability, lineups))
    assert metrics[0].observed_at_utc.tzinfo is timezone.utc
    with pytest.raises(FrozenInstanceError):
        metrics[0].metric_name = "xg"
    with database.connection() as connection:
        for table in ("fixture_context_observations", "team_metric_observations", "player_availability_observations", "lineup_observations"):
            with pytest.raises(Exception):
                connection.execute(f"UPDATE {table} SET provider = 'changed'")
            with pytest.raises(Exception):
                connection.execute(f"DELETE FROM {table}")


@pytest.mark.parametrize("method, fields", [
    ("append_team_metric", {"team_side": "BAD", "metric_name": "xg", "metric_value": 1.0}),
    ("append_team_metric", {"team_side": "HOME", "metric_name": "xg", "metric_value": float("nan")}),
    ("append_team_metric", {"team_side": "HOME", "metric_name": "xg", "metric_value": True}),
    ("append_lineup", {"team_side": "HOME", "lineup_status": "MAYBE"}),
])
def test_evidence_input_rejects_invalid_values(database, fixture_id, method, fields):
    with pytest.raises(ValueError):
        getattr(database, method)(**common(fixture_id, **fields))


def test_evidence_filters_future_boundary_and_backup_restore(database, fixture_id, tmp_path):
    seed(database, fixture_id)
    database.append_team_metric(**common(fixture_id, provider="provider-b", raw_payload_hash="payload-b", team_side="AWAY", metric_name="corners", metric_value=5.0, observed_at_utc="2026-09-08T09:01:00+00:00"))
    repository = ReadRepository(database)
    assert len(repository.list_team_metrics(fixture_id, observed_before=datetime(2026, 9, 8, 9, 0, tzinfo=timezone.utc))) == 1
    assert [item.provider for item in repository.list_team_metrics(fixture_id)] == ["provider-a", "provider-b"]
    with pytest.raises(InvalidReadFilterError):
        repository.list_team_metrics(fixture_id, team_side="BAD")
    evidence_tables = {
        "fixture_context_observations", "team_metric_observations",
        "player_availability_observations", "lineup_observations",
    }
    with database.connection() as connection:
        before = _rows(connection), _table_digests(connection)
    manifest = create_backup(database, tmp_path / "backups")
    restored = restore_backup(manifest, tmp_path / "restored.sqlite3")
    with restored.connection() as connection:
        counts, digests = _rows(connection), _table_digests(connection)
        assert {key: counts[key] for key in evidence_tables} == {key: before[0][key] for key in evidence_tables}
        assert {key: digests[key] for key in evidence_tables} == {key: before[1][key] for key in evidence_tables}
        with pytest.raises(Exception):
            connection.execute("DELETE FROM lineup_observations")


@pytest.mark.parametrize("method, fields", [
    ("append_fixture_context", {"competition_name": "League"}),
    ("append_team_metric", {"team_side": "HOME", "metric_name": "xg", "metric_value": 1.0}),
    ("append_player_availability", {"team_side": "HOME", "player_name": "Player", "availability_status": "OUT"}),
    ("append_lineup", {"team_side": "HOME", "player_name": "Player", "lineup_status": "STARTER"}),
])
def test_evidence_default_idempotency_is_fixture_scoped(database, fixture_id, method, fields):
    second = database.create_fixture(provider="p", provider_fixture_id=f"second-{method}", home_team="H", away_team="A", kickoff_at_utc="2026-09-09T10:00:00+00:00")
    first_id = getattr(database, method)(**common(fixture_id, **fields))
    assert getattr(database, method)(**common(fixture_id, **fields)) == first_id
    second_id = getattr(database, method)(**common(second, **fields))
    assert second_id != first_id
    repository = ReadRepository(database)
    assert len(getattr(repository, {"append_fixture_context": "list_fixture_context", "append_team_metric": "list_team_metrics", "append_player_availability": "list_player_availability", "append_lineup": "list_lineups"}[method])(fixture_id)) == 1
    assert len(getattr(repository, {"append_fixture_context": "list_fixture_context", "append_team_metric": "list_team_metrics", "append_player_availability": "list_player_availability", "append_lineup": "list_lineups"}[method])(second)) == 1


def test_idempotency_conflict_and_player_name_identity(database, fixture_id):
    first = common(fixture_id, team_side="HOME", player_name="One", lineup_status="STARTER", idempotency_key="explicit-key")
    record_id = database.append_lineup(**first)
    with pytest.raises(IdempotencyConflictError):
        database.append_lineup(**{**first, "lineup_status": "BENCH"})
    assert database.append_lineup(**first) == record_id
    one = database.append_lineup(**common(fixture_id, player_name="No Id One", team_side="HOME", lineup_status="STARTER", raw_payload_hash="lineup-one"))
    two = database.append_lineup(**common(fixture_id, player_name="No Id Two", team_side="HOME", lineup_status="STARTER", raw_payload_hash="lineup-one"))
    assert one != two
    for method, fields in (
        (database.append_player_availability, {"team_side": "HOME", "availability_status": "OUT"}),
        (database.append_lineup, {"team_side": "HOME", "lineup_status": "OUT"}),
    ):
        with pytest.raises(ValueError):
            method(**common(fixture_id, **fields))


@pytest.mark.parametrize("field, value", [
    ("provider", ""), ("source_reference", " "), ("raw_payload_hash", ""),
    ("mapping_version", ""), ("validation_status", ""), ("idempotency_key", " "),
    ("idempotency_key", 1),
])
def test_evidence_required_text_and_key_validation(database, fixture_id, field, value):
    with pytest.raises(ValueError):
        database.append_fixture_context(**common(fixture_id, competition_name="League", **{field: value}))
    with pytest.raises(Exception):
        database.append_fixture_context(**common("missing", competition_name="League", raw_payload_hash="other"))


def test_read_evidence_filter_boundaries_and_health(database, fixture_id, tmp_path):
    seed(database, fixture_id)
    repository = ReadRepository(database)
    for bad_limit in (0, 5001, True):
        with pytest.raises(InvalidReadFilterError):
            repository.list_fixture_context(fixture_id, limit=bad_limit)
    with pytest.raises(InvalidReadFilterError):
        repository.list_lineups(fixture_id, observed_before=datetime(2026, 9, 8, 9, 0))
    with pytest.raises(InvalidReadFilterError):
        repository.list_lineups(fixture_id, lineup_status="BAD")
    with pytest.raises(RecordNotFoundError):
        repository.list_fixture_context("missing")
    from data_platform.database import Database
    unverified = Database(tmp_path / "unverified-evidence.sqlite3")
    unverified.initialize()
    with pytest.raises(DatabaseNotHealthyError):
        ReadRepository(unverified)
    database.require_recovery()
    with pytest.raises(DatabaseNotHealthyError):
        ReadRepository(database)
