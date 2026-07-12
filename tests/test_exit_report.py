"""Tests for exit attribution report."""

from polybtc_exit_report import compute_exit_attribution, _normalise_reason


def test_normalise_reason_families():
    assert _normalise_reason("stop_loss_25pct") == "stop_loss"
    assert _normalise_reason("early_cut_underwater_0.050") == "early_cut_underwater"
    assert _normalise_reason("early_cut_btc_reverse_-40") == "early_cut_btc_reverse"
    assert _normalise_reason("hold_to_resolve_time_exit_3s") == "hold_to_resolve_time_exit"
    assert _normalise_reason("time_exit_20s_before_end") == "time_exit"
    assert _normalise_reason(None) == "unknown"


def test_exit_attribution_by_reason():
    trades = [
        {"pnl": 1.5, "close_reason": "time_exit_20s_before_end", "side": "UP"},
        {"pnl": -5.0, "close_reason": "stop_loss_25pct", "side": "UP"},
        {"pnl": -2.0, "close_reason": "early_cut_underwater_0.040", "side": "DOWN"},
        {"pnl": 0.8, "close_reason": "hold_to_resolve_time_exit_3s", "side": "UP"},
        {"pnl": -5.0, "close_reason": "stop_loss_25pct", "side": "DOWN"},
    ]
    out = compute_exit_attribution(trades)
    assert out["n_trades"] == 5
    assert out["by_reason"]["stop_loss"]["trades"] == 2
    assert out["by_reason"]["stop_loss"]["net_pnl"] == -10.0
    assert out["worst_reason"] == "stop_loss"
    assert "time_exit" in out["by_reason"]
    assert out["by_reason"]["time_exit"]["expectancy"] == 1.5
