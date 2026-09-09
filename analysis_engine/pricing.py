import math

from .exceptions import InvalidOddsError, InvalidProbabilityError


SUPPORTED_MARKETS = frozenset({"1x2", "moneyline", "btts"})


def valid_odds(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 1:
        raise InvalidOddsError("decimal odds must be finite, non-bool, and exceed 1")
    return float(value)


def valid_probability(value: object, *, penalty: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise InvalidProbabilityError("probability/penalty must be finite and non-bool")
    value = float(value)
    if not (0 <= value <= 1 if penalty else 0 < value < 1):
        raise InvalidProbabilityError("probability or penalty is out of range")
    return value


def supports_binary_market(market_type: str, settlement_type: str) -> bool:
    return market_type.lower() in SUPPORTED_MARKETS and settlement_type.lower() == "normal"


def devig(odds: tuple[float, ...]) -> tuple[float, ...]:
    implied = tuple(1 / valid_odds(value) for value in odds)
    overround = sum(implied)
    if overround <= 0: raise InvalidOddsError("overround must be positive")
    result = tuple(value / overround for value in implied)
    if abs(sum(result) - 1) > 1e-9: raise InvalidOddsError("invalid de-vig result")
    return result
