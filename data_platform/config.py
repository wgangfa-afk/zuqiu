"""Environment-only configuration. No credentials belong in this module."""

from __future__ import annotations

import os
from dataclasses import dataclass


DEFAULT_DATABASE_URL = "sqlite:///football_quant.sqlite3"
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_LOG_LEVEL = "INFO"


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str = DEFAULT_DATABASE_URL
    timezone: str = DEFAULT_TIMEZONE
    log_level: str = DEFAULT_LOG_LEVEL
    odds_provider: str | None = None
    fixture_provider: str | None = None
    results_provider: str | None = None
    odds_min_remaining_credits: int = 0
    odds_regions: str | None = None

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            database_url=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
            timezone=os.getenv("TIMEZONE", DEFAULT_TIMEZONE),
            log_level=os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL),
            odds_provider=os.getenv("ODDS_PROVIDER") or None,
            fixture_provider=os.getenv("FIXTURE_PROVIDER") or None,
            results_provider=os.getenv("RESULTS_PROVIDER") or None,
            odds_min_remaining_credits=int(os.getenv("THE_ODDS_MIN_REMAINING_CREDITS", "0")),
            odds_regions=os.getenv("THE_ODDS_REGIONS") or None,
        )

    def sqlite_path(self) -> str:
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            raise ValueError("Alpha Foundation supports SQLite DATABASE_URL values only")
        return self.database_url.removeprefix(prefix)
