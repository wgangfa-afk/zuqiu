"""Provider-neutral, non-analytical ingestion interfaces."""

from .exceptions import IngestionError, ProviderAuthenticationError, ProviderPayloadError, ProviderRateLimitError, QuotaProtectionError
from .service import OddsIngestionService

__all__ = ["IngestionError", "OddsIngestionService", "ProviderAuthenticationError", "ProviderPayloadError", "ProviderRateLimitError", "QuotaProtectionError"]
