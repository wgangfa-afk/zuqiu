import pytest

from data_platform.domain import SettlementOutcome
from data_platform.settlement import (
    pnl_for,
    settle_asian_corners_total,
    settle_asian_handicap,
    settle_asian_total,
    settle_three_way_corners,
    split_asian_line,
)


@pytest.mark.parametrize(
    ("difference", "line", "expected"),
    [
        (0, -0.25, SettlementOutcome.HALF_LOSS),
        (1, -0.25, SettlementOutcome.WIN),
        (1, -0.75, SettlementOutcome.HALF_WIN),
        (2, -0.75, SettlementOutcome.WIN),
        (0, 0.25, SettlementOutcome.HALF_WIN),
        (-1, 0.25, SettlementOutcome.LOSS),
        (0, 0.75, SettlementOutcome.WIN),
        (-1, 0.75, SettlementOutcome.HALF_LOSS),
        (0, 0, SettlementOutcome.PUSH),
        (0, 0.5, SettlementOutcome.WIN),
        (1, -1, SettlementOutcome.PUSH),
        (1, -1.25, SettlementOutcome.HALF_LOSS),
        (2, -1.25, SettlementOutcome.WIN),
        (2, -1.75, SettlementOutcome.HALF_WIN),
        (2, -2, SettlementOutcome.PUSH),
    ],
)
def test_asian_handicap_settlement(difference, line, expected):
    assert settle_asian_handicap(difference, line) is expected


@pytest.mark.parametrize(
    ("total", "line", "selection", "expected"),
    [
        (2, 2, "over", SettlementOutcome.PUSH),
        (2, 2.25, "over", SettlementOutcome.HALF_LOSS),
        (3, 2.25, "over", SettlementOutcome.WIN),
        (3, 2.75, "over", SettlementOutcome.HALF_WIN),
        (2, 2.75, "over", SettlementOutcome.LOSS),
        (2, 2.25, "under", SettlementOutcome.HALF_WIN),
        (3, 2.75, "under", SettlementOutcome.HALF_LOSS),
        (3, 3, "under", SettlementOutcome.PUSH),
    ],
)
def test_asian_total_settlement(total, line, selection, expected):
    assert settle_asian_total(total, line, selection) is expected


def test_quarter_line_is_split_mathematically():
    assert split_asian_line(-0.75) == (pytest.approx(-1.0), pytest.approx(-0.5))


def test_three_way_corner_over_eight_loses_at_eight():
    assert settle_three_way_corners(8, 8, "over") is SettlementOutcome.LOSS
    assert settle_three_way_corners(8, 8, "exactly") is SettlementOutcome.WIN
    assert settle_asian_corners_total(8, 8, "over") is SettlementOutcome.PUSH


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (SettlementOutcome.WIN, 0.9),
        (SettlementOutcome.HALF_WIN, 0.45),
        (SettlementOutcome.PUSH, 0.0),
        (SettlementOutcome.HALF_LOSS, -0.5),
        (SettlementOutcome.LOSS, -1.0),
    ],
)
def test_pnl_math(outcome, expected):
    assert pnl_for(1, 1.9, outcome) == pytest.approx(expected)
