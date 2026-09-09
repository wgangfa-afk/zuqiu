from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True, slots=True)
class ProviderOutcome: name: str; price: float
@dataclass(frozen=True, slots=True)
class ProviderMarket: key: str; outcomes: tuple[ProviderOutcome, ...]
@dataclass(frozen=True, slots=True)
class ProviderBookmaker: key: str; last_update: datetime | None; markets: tuple[ProviderMarket, ...]
@dataclass(frozen=True, slots=True)
class ProviderEvent: id: str; sport_key: str; sport_title: str; commence_time: datetime; home_team: str; away_team: str; bookmakers: tuple[ProviderBookmaker, ...] = ()
@dataclass(frozen=True, slots=True)
class QuotaSnapshot: remaining: int | None; used: int | None; last: int | None
@dataclass(frozen=True, slots=True)
class IngestionResult: records_received: int; records_written: int; records_rejected: int; quota: QuotaSnapshot
