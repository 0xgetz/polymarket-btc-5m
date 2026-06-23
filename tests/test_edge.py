"""Tests for the edge / break-even calculator."""
import math

import pytest

from polybtc_edge import (
    win_payoff,
    breakeven_winrate,
    ev_per_stake,
    expected_value,
    edge,
    breakeven_table,
)


def test_breakeven_equals_entry_price():
    for p in (0.55, 0.70, 0.71, 0.90):
        assert breakeven_winrate(p) == p


def test_win_payoff_known_value():
    assert win_payoff(0.71, 5.0) == pytest.approx(5 * 0.29 / 0.71, rel=1e-9)
    assert win_payoff(0.50, 5.0) == pytest.approx(5.0)  # even-money


def test_ev_zero_at_breakeven():
    assert ev_per_stake(0.71, 0.71) == pytest.approx(0.0, abs=1e-12)


def test_ev_sign_tracks_edge():
    assert ev_per_stake(0.71, 0.80) > 0
    assert ev_per_stake(0.71, 0.60) < 0


def test_edge_value():
    assert edge(0.70, 0.80) == pytest.approx(0.10)
    assert edge(0.90, 0.80) == pytest.approx(-0.10)


def test_expected_value_scales_with_stake():
    one = expected_value(0.71, 0.80, 1.0)
    ten = expected_value(0.71, 0.80, 10.0)
    assert ten == pytest.approx(one * 10)


def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        win_payoff(0.0)
    with pytest.raises(ValueError):
        breakeven_winrate(1.0)
    with pytest.raises(ValueError):
        ev_per_stake(0.7, 1.5)


def test_breakeven_table_shape():
    rows = breakeven_table(stake=5.0)
    assert rows and all({"entry", "breakeven_winrate", "win_payoff_usd"} <= set(r) for r in rows)
    row71 = next(r for r in rows if r["entry"] == 0.71)
    assert row71["breakeven_winrate"] == 0.71
