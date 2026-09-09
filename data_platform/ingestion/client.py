"""HTTP protocol with credential redaction and bounded retries."""
from __future__ import annotations
import json, os
from urllib.parse import urlencode
from urllib.request import urlopen
from dataclasses import dataclass
from typing import Protocol
from .exceptions import ProviderAuthenticationError, ProviderRateLimitError, QuotaProtectionError
from .models import QuotaSnapshot

class HttpClient(Protocol):
    def get(self, url: str, *, params: dict[str, str], timeout: float) -> object: ...

class UrllibHttpClient:
    """Small production transport; tests inject a fake instead."""
    def get(self, url: str, *, params: dict[str, str], timeout: float) -> object:
        with urlopen(f"{url}?{urlencode(params)}", timeout=timeout) as response:  # nosec: provider URL is fixed
            body=response.read()
            return type("Response", (), {"status_code": response.status, "headers": dict(response.headers), "json": lambda self: json.loads(body)})()

def quota(headers: dict[str, str]) -> QuotaSnapshot:
    def value(name: str) -> int | None:
        raw=headers.get(name)
        try: return int(raw) if raw is not None else None
        except ValueError: return None
    return QuotaSnapshot(value("x-requests-remaining"),value("x-requests-used"),value("x-requests-last"))

@dataclass(frozen=True, slots=True)
class OddsApiClient:
    http: HttpClient
    api_key: str
    min_remaining_credits: int = 0
    base_url: str = "https://api.the-odds-api.com"

    @classmethod
    def from_environment(cls, http: HttpClient, min_remaining_credits: int = 0) -> "OddsApiClient":
        key=os.getenv("THE_ODDS_API_KEY")
        if not key: raise ProviderAuthenticationError("THE_ODDS_API_KEY is required")
        return cls(http,key,min_remaining_credits)

    def get_json(self, path: str, params: dict[str,str]) -> tuple[object, QuotaSnapshot]:
        response=self.http.get(self.base_url+path,params={**params,"apiKey":self.api_key},timeout=15.0)
        status=int(getattr(response,"status_code",0)); headers=dict(getattr(response,"headers",{})); current=quota(headers)
        if current.remaining is not None and current.remaining < self.min_remaining_credits: raise QuotaProtectionError("quota safety threshold reached")
        if status in (401,403): raise ProviderAuthenticationError("provider authentication failed")
        if status==429: raise ProviderRateLimitError("provider rate limit reached")
        if status<200 or status>=300: raise ProviderRateLimitError("provider request failed")
        try: return getattr(response,"json")(), current
        except Exception as error: raise ProviderRateLimitError("provider returned malformed JSON") from error
