"""Pure settlement functions. Lines are decimal Asian lines, never display text."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from .domain import SettlementOutcome, SettlementResult


def _decimal(value: float | Decimal) -> Decimal:
    return Decimal(str(value))


def split_asian_line(line: float | Decimal) -> tuple[Decimal, ...]:
    """Return the one or two half-stake component lines for an Asian line."""
    value = _decimal(line)
    quarters = (value * 4).to_integral_value(rounding=ROUND_HALF_UP)
    if value * 4 != quarters:
        raise ValueError("Asian lines must be whole, half, or quarter increments")
    if int(quarters) % 2:
        return (value - Decimal("0.25"), value + Decimal("0.25"))
    return (value,)


def _component_outcome(metric: Decimal, line: Decimal) -> SettlementOutcome:
    adjusted = metric + line
    if adjusted > 0:
        return SettlementOutcome.WIN
    if adjusted < 0:
        return SettlementOutcome.LOSS
    return SettlementOutcome.PUSH


def _combine(outcomes: tuple[SettlementOutcome, ...]) -> SettlementOutcome:
    if len(outcomes) == 1:
        return outcomes[0]
    pair = set(outcomes)
    if pair == {SettlementOutcome.WIN}:
        return SettlementOutcome.WIN
    if pair == {SettlementOutcome.LOSS}:
        return SettlementOutcome.LOSS
    if pair == {SettlementOutcome.PUSH}:
        return SettlementOutcome.PUSH
    if pair == {SettlementOutcome.WIN, SettlementOutcome.PUSH}:
        return SettlementOutcome.HALF_WIN
    if pair == {SettlementOutcome.LOSS, SettlementOutcome.PUSH}:
        return SettlementOutcome.HALF_LOSS
    raise ValueError("Invalid Asian component outcome combination")


def settle_asian_handicap(goal_difference: int, handicap: float | Decimal) -> SettlementOutcome:
    """Settle from the selected team's score difference (selected - opponent)."""
    metric = Decimal(goal_difference)
    return _combine(tuple(_component_outcome(metric, part) for part in split_asian_line(handicap)))


def settle_asian_total(total: int, line: float | Decimal, selection: str) -> SettlementOutcome:
    """Settle an Asian total. `selection` must be `over` or `under`."""
    if selection not in {"over", "under"}:
        raise ValueError("Asian total selection must be 'over' or 'under'")
    total_value = Decimal(total)
    metric_sign = Decimal(1) if selection == "over" else Decimal(-1)
    outcomes = tuple(
        _component_outcome(metric_sign * (total_value - part), Decimal(0))
        for part in split_asian_line(line)
    )
    return _combine(outcomes)


def settle_three_way_corners(total_corners: int, line: int, selection: str) -> SettlementOutcome:
    """Strict three-way corner settlement; exact totals are never an Asian push."""
    if selection not in {"over", "exactly", "under"}:
        raise ValueError("Three-way selection must be over, exactly, or under")
    is_winner = {
        "over": total_corners > line,
        "exactly": total_corners == line,
        "under": total_corners < line,
    }[selection]
    return SettlementOutcome.WIN if is_winner else SettlementOutcome.LOSS


def settle_asian_corners_total(total_corners: int, line: float | Decimal, selection: str) -> SettlementOutcome:
    return settle_asian_total(total_corners, line, selection)


def settle_corner_handicap(corner_difference: int, handicap: float | Decimal) -> SettlementOutcome:
    return settle_asian_handicap(corner_difference, handicap)


def pnl_for(stake_u: float, odds: float, outcome: SettlementOutcome) -> float:
    stake = _decimal(stake_u)
    price = _decimal(odds)
    multipliers = {
        SettlementOutcome.WIN: price - 1,
        SettlementOutcome.HALF_WIN: (price - 1) / 2,
        SettlementOutcome.PUSH: Decimal(0),
        SettlementOutcome.HALF_LOSS: Decimal("-0.5"),
        SettlementOutcome.LOSS: Decimal(-1),
    }
    return float(stake * multipliers[outcome])


def settlement_result(stake_u: float, odds: float, outcome: SettlementOutcome) -> SettlementResult:
    return SettlementResult(outcome=outcome, net_pnl=pnl_for(stake_u, odds, outcome))
