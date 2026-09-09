class IngestionError(RuntimeError):
    """Safe ingestion failure; messages never contain credentials."""


class ProviderAuthenticationError(IngestionError): pass
class ProviderRateLimitError(IngestionError): pass
class ProviderPayloadError(IngestionError): pass
class QuotaProtectionError(IngestionError): pass
