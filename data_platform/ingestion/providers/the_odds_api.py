"""Strict V4 response parsing; transport is injected by the caller."""
from datetime import datetime, timezone
import math
from ..exceptions import ProviderPayloadError
from ..models import ProviderBookmaker, ProviderEvent, ProviderMarket, ProviderOutcome

def utc(value: object) -> datetime:
    if not isinstance(value, str): raise ProviderPayloadError("provider timestamp is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None: raise ProviderPayloadError("provider timestamp is naive")
    return parsed.astimezone(timezone.utc)

def parse_events(payload: object, *, odds: bool = False) -> tuple[ProviderEvent, ...]:
    if not isinstance(payload, list): raise ProviderPayloadError("provider response must be a JSON array")
    events=[]
    for item in payload:
        if not isinstance(item, dict): raise ProviderPayloadError("provider event is invalid")
        try:
            bookmakers=[]
            for book in item.get("bookmakers", []):
                markets=[]
                for market in book.get("markets", []):
                    outcomes=[]
                    for outcome in market.get("outcomes", []):
                        price=outcome["price"]
                        if isinstance(price,bool) or not isinstance(price,(int,float)) or not math.isfinite(price) or price<=1: raise ProviderPayloadError("decimal odds are invalid")
                        outcomes.append(ProviderOutcome(str(outcome["name"]), float(price)))
                    markets.append(ProviderMarket(str(market["key"]),tuple(outcomes)))
                bookmakers.append(ProviderBookmaker(str(book["key"]), utc(book["last_update"]) if book.get("last_update") else None, tuple(markets)))
            events.append(ProviderEvent(str(item["id"]),str(item["sport_key"]),str(item.get("sport_title", item["sport_key"])),utc(item["commence_time"]),str(item["home_team"]),str(item["away_team"]),tuple(bookmakers)))
        except (KeyError, TypeError, ValueError) as error: raise ProviderPayloadError("provider event schema is invalid") from error
    return tuple(events)
