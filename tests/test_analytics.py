"""Tests for trade analytics / log backtest stats."""
import pytest

from polybtc_analytics import compute_stats


def _trades(pnls, sides=None):
    sides = sides or [None] * len(pnls)
    return [{"pnl": p, "side": s} for p, s in zip(pnls, sides)]


def test_empty_input():
    out = compute_stats([])
    assert out["n_trades"] == 0


def test_basic_counts_and_winrate():
    out = compute_stats(_trades([2.0, 2.0, -5.0, 2.0]))
    assert out["n_trades"] == 4
    assert out["wins"] == 3 and out["losses"] == 1
    assert out["win_rate"] == pytest.approx(0.75)
    assert out["net_pnl"] == pytest.approx(1.0)


def test_profit_factor_and_averages():
    out = compute_stats(_trades([3.0, -1.0, -2.0]))
    assert out["gross_profit"] == pytest.approx(3.0)
    assert out["gross_loss"] == pytest.approx(3.0)
    assert out["profit_factor"] == pytest.approx(1.0)
    assert out["avg_win"] == pytest.approx(3.0)
    assert out["avg_loss"] == pytest.approx(-1.5)


def test_profit_factor_infinite_without_losses():
    out = compute_stats(_trades([1.0, 2.0]))
    assert out["profit_factor"] == float("inf")


def test_max_drawdown():
    # equity path: +2, -3(=-1 from peak2 -> dd3), +1 ...
    out = compute_stats(_trades([2.0, -5.0, 1.0]))
    # peak after first = 2, trough after second = -3 => drawdown = 5
    assert out["max_drawdown"] == pytest.approx(5.0)


def test_streaks():
    out = compute_stats(_trades([-1, -1, -1, 2, 2, -1]))
    assert out["max_consecutive_losses"] == 3
    assert out["max_consecutive_wins"] == 2


def test_by_side_breakdown():
    out = compute_stats(_trades([2.0, -5.0, 2.0], sides=["UP", "UP", "DOWN"]))
    assert out["by_side"]["UP"]["trades"] == 2
    assert out["by_side"]["UP"]["wins"] == 1
    assert out["by_side"]["UP"]["win_rate"] == pytest.approx(0.5)
    assert out["by_side"]["DOWN"]["net_pnl"] == pytest.approx(2.0)


def test_breakeven_trades_excluded_from_winrate():
    out = compute_stats(_trades([0.0, 2.0, -5.0]))
    assert out["breakeven"] == 1
    # decided = 1 win + 1 loss -> win_rate 0.5
    assert out["win_rate"] == pytest.approx(0.5)
