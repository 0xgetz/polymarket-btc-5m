"""Tests for the dry-run (paper trading) recorder."""
import datetime as dt

import pytest

import polybtc_config as cfgmod
from polybtc_preflight import MarketSnapshot
from polybtc_dryrun import simulate_trade, write_paper_log
from polybtc_edge import win_payoff
from polybtc_analytics import load_runs_from_logs, compute_stats


@pytest.fixture(scope="module")
def profile():
    return cfgmod.get_profile(cfgmod.load_config(), "conservative")


def _good_market(profile, **ov):
    base = dict(
        seconds_left=profile["entry_window_seconds_left_target"],
        btc_move_usd=profile["btc_move_usd_min"] + 10,
        up_ask=max(0.71, profile["threshold_price"]),
        dn_ask=0.29,
        spread=profile["skip_if_spread_gt"] / 2,
        top_ask_notional_usd=profile["skip_if_top_ask_notional_usd_lt"] + 10,
        quote_age_sec=1.0,
    )
    base.update(ov)
    return MarketSnapshot(**base)


def test_win_outcome_pnl(profile):
    rec = simulate_trade(profile, _good_market(profile), "win", market_slug="slug-1")
    assert rec["result"] == "win"
    assert rec["opened"]["side"] == "UP"
    expected = round(win_payoff(rec["opened"]["entry_price"], rec["opened"]["stake_usd"]), 6)
    assert rec["realized_cashflow_pnl_usdc"] == expected
    assert rec["realized_cashflow_pnl_usdc"] > 0


def test_loss_outcome_pnl(profile):
    rec = simulate_trade(profile, _good_market(profile), "loss")
    assert rec["result"] == "loss"
    assert rec["realized_cashflow_pnl_usdc"] == -rec["opened"]["stake_usd"]


def test_side_outcome_win_and_loss(profile):
    m = _good_market(profile)  # decision side will be UP
    win = simulate_trade(profile, m, "UP")
    loss = simulate_trade(profile, m, "DOWN")
    assert win["result"] == "win" and win["realized_cashflow_pnl_usdc"] > 0
    assert loss["result"] == "loss" and loss["realized_cashflow_pnl_usdc"] < 0


def test_no_entry_when_preflight_fails(profile):
    rec = simulate_trade(profile, _good_market(profile, top_ask_notional_usd=1.0), "win")
    assert rec["result"] == "no_entry"
    assert "realized_cashflow_pnl_usdc" not in rec
    assert rec["opened"] is None


def test_invalid_outcome_raises(profile):
    with pytest.raises(ValueError):
        simulate_trade(profile, _good_market(profile), "sideways")


def test_write_and_read_back_via_analytics(profile, tmp_path):
    runtime = str(tmp_path / "runtime")
    base = dt.datetime(2026, 1, 1, 12, 0, 0, tzinfo=dt.timezone.utc)
    outcomes = ["win", "win", "loss"]
    for i, o in enumerate(outcomes):
        rec = simulate_trade(profile, _good_market(profile), o, market_slug=f"s{i}")
        write_paper_log(rec, runtime, ts=base + dt.timedelta(seconds=i))
    trades = load_runs_from_logs(runtime)
    assert len(trades) == 3
    stats = compute_stats(trades)
    assert stats["wins"] == 2 and stats["losses"] == 1
    assert stats["win_rate"] == pytest.approx(0.6667, abs=1e-4)
