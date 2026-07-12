"""Tests for fill / slippage report."""

from polybtc_fill_report import compute_fill_stats, slippage_bps


def test_slippage_bps_worse_for_buyer():
    # Paid 0.72 vs signal 0.70 → +~285.7 bps
    bps = slippage_bps(0.70, 0.72)
    assert bps > 0
    assert abs(bps - (0.02 / 0.70 * 10000)) < 0.01


def test_fill_stats_aggregate():
    fills = [
        {"signal_price": 0.70, "fill_price": 0.70, "side": "UP", "pnl": 1.0},
        {"signal_price": 0.70, "fill_price": 0.72, "side": "UP", "pnl": -5.0},
        {"signal_price": 0.80, "fill_price": 0.79, "side": "DOWN", "pnl": 0.5},
    ]
    out = compute_fill_stats(fills)
    assert out["n_fills"] == 3
    assert out["avg_slippage_bps"] is not None
    assert out["pct_worse_than_signal"] > 0
    assert "UP" in out["by_side"]
    assert len(out["worst_fills"]) >= 1
