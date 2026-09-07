from __future__ import annotations

import pytest

from data_platform.database import Database
from data_platform.recovery import startup_integrity_check


@pytest.fixture()
def database(tmp_path):
    db = Database(tmp_path / "alpha.sqlite3")
    db.initialize()
    assert startup_integrity_check(db).ok
    return db


@pytest.fixture()
def fixture_id(database):
    return database.create_fixture(
        provider="synthetic-test-provider",
        provider_fixture_id="fixture-1",
        home_team="Home",
        away_team="Away",
        kickoff_at_utc="2026-09-08T10:00:00+00:00",
    )
