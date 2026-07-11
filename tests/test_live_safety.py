"""Unit tests for live-path safety helpers (no network)."""
from __future__ import annotations

import polybtc_live_safety as safety
from polybtc_config import get_profile, load_config


def test_close_limit_respects_floor_when_bid_missing():
    px = safety.close_limit_price(0.80, None, max_slippage_from_entry=0.50)
    # floor = 0.80 * 0.5 = 0.40
    assert px == 0.40


def test_close_limit_does_not_dump_to_one_cent_when_bid_low():
    px = safety.close_limit_price(0.80, 0.02, aggressive_offset=0.01, max_slippage_from_entry=0.50)
    assert px >= 0.40
    assert px > 0.01


def test_close_limit_uses_bid_when_above_floor():
    px = safety.close_limit_price(0.80, 0.70, aggressive_offset=0.01, max_slippage_from_entry=0.50)
    assert abs(px - 0.69) < 1e-9


def test_open_execution_env_never_disables_guards():
    cfg = load_config()
    prof = get_profile(cfg, "conservative")
    env = safety.open_execution_env(prof, {})
    assert float(env["PM_MAX_SPREAD"]) == float(prof["skip_if_spread_gt"])
    assert float(env["PM_MIN_TOP_ASK_NOTIONAL_USD"]) == float(prof["skip_if_top_ask_notional_usd_lt"])
    assert env["PM_MAX_SPREAD"] != "1" or prof["skip_if_spread_gt"] == 1
    assert env["PM_MIN_TOP_ASK_NOTIONAL_USD"] != "0" or prof["skip_if_top_ask_notional_usd_lt"] == 0


def test_open_execution_env_preserves_operator_overrides():
    env = safety.open_execution_env(
        {"skip_if_spread_gt": 0.03, "skip_if_top_ask_notional_usd_lt": 30},
        {"PM_MAX_SPREAD": "0.02", "PM_MIN_TOP_ASK_NOTIONAL_USD": "50"},
    )
    assert env["PM_MAX_SPREAD"] == "0.02"
    assert env["PM_MIN_TOP_ASK_NOTIONAL_USD"] == "50"


def test_guard_state_from_pnls_blocks_after_streak():
    cfg = load_config()
    prof = get_profile(cfg, "conservative")
    state = safety.build_guard_state_from_pnls([-5, -5, -5])
    out = safety.guards_allow_entry(prof, state, account_equity=200)
    assert out["allowed"] is False
    assert out["checks"]["consecutive_losses"] is False


def test_stop_loss_price():
    assert abs(safety.stop_loss_price(0.80, 0.25) - 0.60) < 1e-9


def test_pnls_for_today_filters_by_day():
    import datetime as dt
    import time

    today = safety.today_utc()
    now = time.time()
    # yesterday
    y = now - 86400
    trades = [
        {"pnl": -5.0, "ts": now},
        {"pnl": 2.0, "ts": y},
    ]
    pnls = safety.pnls_for_today_from_trades(trades, day=today)
    assert pnls == [-5.0]
