from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from data_platform.read_api import InvalidReadFilterError, ReadRepository
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
