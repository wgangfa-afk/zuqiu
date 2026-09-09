from dataclasses import dataclass
import pytest
from data_platform.ingestion.exceptions import ProviderAuthenticationError, ProviderPayloadError
from data_platform.ingestion.models import QuotaSnapshot
from data_platform.ingestion.providers.the_odds_api import parse_events
from data_platform.ingestion.service import OddsIngestionService

PAYLOAD=[{"id":"event-1","sport_key":"soccer_test","sport_title":"Test","commence_time":"2026-09-09T12:00:00Z","home_team":"Home","away_team":"Away","bookmakers":[{"key":"book-a","last_update":"2026-09-09T10:00:00Z","markets":[{"key":"h2h","outcomes":[{"name":"Home","price":2.0},{"name":"Away","price":3.0},{"name":"Draw","price":3.2}]}]}]}]

class Client:
    def get_json(self,path,params): return PAYLOAD, QuotaSnapshot(10,1,1)

def test_soccer_h2h_parse_and_atomic_idempotent_commit(database):
    service=OddsIngestionService(database,Client())
    assert service.plan("soccer_test","eu")["markets"]=="h2h"
    assert service.ingest(sport="soccer_test",regions="eu",mode="dry-run").records_written==0
    first=service.ingest(sport="soccer_test",regions="eu",mode="commit")
    second=service.ingest(sport="soccer_test",regions="eu",mode="commit")
    assert (first.records_written,second.records_written)==(3,0)
    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM fixtures").fetchone()[0]==1
        assert connection.execute("SELECT COUNT(*) FROM market_snapshots").fetchone()[0]==3
        assert connection.execute("SELECT COUNT(*) FROM raw_provider_payloads").fetchone()[0]==1

@pytest.mark.parametrize("outcomes", [[{"name":"Home","price":2.0},{"name":"Away","price":2.0}], [{"name":"Home","price":2.0},{"name":"Home","price":2.0},{"name":"Draw","price":3.0}]])
def test_invalid_h2h_group_rejected_without_partial_snapshots(database,outcomes):
    payload=[{**PAYLOAD[0],"bookmakers":[{**PAYLOAD[0]["bookmakers"][0],"markets":[{"key":"h2h","outcomes":outcomes}]}]}]
    class InvalidClient:
        def get_json(self,path,params): return payload,QuotaSnapshot(10,1,1)
    result=OddsIngestionService(database,InvalidClient()).ingest(sport="soccer_test",regions="eu",mode="commit")
    assert result.records_written==0 and result.records_rejected==1
    with database.connection() as connection: assert connection.execute("SELECT COUNT(*) FROM market_snapshots").fetchone()[0]==0

def test_payload_validation_rejects_naive_and_invalid_odds():
    broken=[{**PAYLOAD[0],"commence_time":"2026-09-09T12:00:00"}]
    with pytest.raises(ProviderPayloadError): parse_events(broken)
