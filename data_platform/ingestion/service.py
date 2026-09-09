"""Atomic factual h2h ingestion; deliberately contains no analysis logic."""
from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from uuid import uuid4
from data_platform.database import Database, normalize_utc
from .exceptions import ProviderPayloadError
from .models import IngestionResult, ProviderEvent, QuotaSnapshot
from .providers.the_odds_api import parse_events

def canonical(value: object) -> str: return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=True)
def digest(value: object) -> str: return hashlib.sha256(canonical(value).encode()).hexdigest()

class OddsIngestionService:
    def __init__(self,database: Database, client: object) -> None: self.database,self.client=database,client
    def plan(self, sport: str, regions: str) -> dict[str,object]:
        return {"sport":sport,"regions":regions,"markets":"h2h","oddsFormat":"decimal","dateFormat":"iso","estimated_max_cost":len(regions.split(","))}
    def ingest(self, *, sport: str, regions: str, mode: str="dry-run") -> IngestionResult:
        if mode not in {"dry-run","commit"}: raise ValueError("mode must be dry-run or commit")
        if not sport.startswith("soccer_"): raise ProviderPayloadError("Phase 1 only ingests soccer sport keys")
        payload, quota = self.client.get_json(f"/v4/sports/{sport}/odds", {"regions":regions,"markets":"h2h","oddsFormat":"decimal","dateFormat":"iso"})
        events=parse_events(payload,odds=True)
        valid,rejected=self._mapped(events)
        if mode=="dry-run": return IngestionResult(len(events),0,rejected,quota)
        self.database._assert_writable()
        payload_json=canonical(payload); payload_hash=hashlib.sha256(payload_json.encode()).hexdigest(); now=datetime.now(timezone.utc).isoformat()
        with self.database.connection() as connection:
            run_id=str(uuid4())
            request_fingerprint = digest({"sport":sport,"regions":regions})
            existing_run = connection.execute("SELECT 1 FROM ingestion_runs WHERE provider='the_odds_api' AND request_fingerprint=? AND raw_payload_hash=?", (request_fingerprint, payload_hash)).fetchone()
            if existing_run is not None:
                return IngestionResult(len(events), 0, rejected, quota)
            expected_written = sum(3 for event, book, outcomes, observed in valid for selection, odds in outcomes if not connection.execute("SELECT 1 FROM ingested_snapshot_keys WHERE idempotency_key=?", (digest({"provider":"the_odds_api","event":event.id,"bookmaker":book,"market":"h2h","selection":selection,"line":None,"updated":observed,"odds":odds,"mapping":"v1"}),)).fetchone())
            connection.execute("INSERT INTO ingestion_runs VALUES (?, 'the_odds_api', ?, 'odds', ?, ?, ?, 'completed', 200, ?, ?, ?, NULL, ?, ?, ?, ?)",(run_id,sport,request_fingerprint,now,now,len(events),expected_written,rejected,quota.remaining,quota.used,quota.last,payload_hash))
            existing=connection.execute("SELECT id FROM raw_provider_payloads WHERE provider='the_odds_api' AND payload_sha256=?",(payload_hash,)).fetchone()
            if existing is None: connection.execute("INSERT INTO raw_provider_payloads VALUES (?, ?, 'the_odds_api', 'application/json', ?, ?, ?)",(str(uuid4()),run_id,payload_json,payload_hash,now))
            written=0
            for event,book,outcomes,observed in valid:
                fixture=connection.execute("SELECT id FROM fixtures WHERE provider='the_odds_api' AND provider_fixture_id=?",(event.id,)).fetchone()
                fixture_id=fixture[0] if fixture else str(uuid4())
                if fixture is None: connection.execute("INSERT INTO fixtures VALUES (?, 'the_odds_api', ?, ?, ?, ?, ?)",(fixture_id,event.id,event.home_team,event.away_team,event.commence_time.isoformat(),now))
                for selection, odds in outcomes:
                    key=digest({"provider":"the_odds_api","event":event.id,"bookmaker":book,"market":"h2h","selection":selection,"line":None,"updated":observed,"odds":odds,"mapping":"v1"})
                    if connection.execute("SELECT 1 FROM ingested_snapshot_keys WHERE idempotency_key=?",(key,)).fetchone(): continue
                    snapshot_id=str(uuid4()); source=f"the_odds_api://{sport}/events/{event.id}/bookmakers/{book}/markets/h2h"
                    connection.execute("INSERT INTO market_snapshots VALUES (?, ?, ?, ?, '1x2', 'normal', ?, NULL, ?, ?, ?, ?, 'VALID', 'v1')",(snapshot_id,fixture_id,f"the_odds_api:{book}",source,selection,odds,observed,now,payload_hash))
                    connection.execute("INSERT INTO ingested_snapshot_keys VALUES (?, ?)",(key,snapshot_id)); written+=1
        return IngestionResult(len(events),written,rejected,quota)
    def _mapped(self, events: tuple[ProviderEvent,...]):
        valid=[]; rejected=0
        for event in events:
            for book in event.bookmakers:
                for market in book.markets:
                    if market.key!="h2h": continue
                    mapping={event.home_team:"home",event.away_team:"away","Draw":"draw"}
                    choices=[]
                    for outcome in market.outcomes:
                        if outcome.name not in mapping: choices=[]; break
                        choices.append((mapping[outcome.name],outcome.price))
                    if {item[0] for item in choices}!={"home","away","draw"} or len(choices)!=3: rejected+=1; continue
                    valid.append((event,book.key,tuple(choices),(book.last_update or datetime.now(timezone.utc)).isoformat()))
        return valid,rejected
