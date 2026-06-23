"""Tests for capital-protection guardrails."""
import pytest

from polybtc_guardrails import (
    GuardState,
    new_state,
    register_result,
    daily_loss_cap_usd,
    check_guards,
    ev_gate,
)

PROFILE = {
    "max_consecutive_losses": 3,
    "max_trades_per_day": 5,
    "daily_max_loss_pct": 10,
    "min_edge": 0.02,
}


def test_register_result_streak_logic():
    s = new_state(day="2026-01-01")
    s = register_result(s, -5, day="2026-01-01")
    s = register_result(s, -5, day="2026-01-01")
    assert s.consecutive_losses == 2 and s.trades_today == 2
    s = register_result(s, +2, day="2026-01-01")  # win resets streak
    assert s.consecutive_losses == 0 and s.trades_today == 3
    s = register_result(s, 0, day="2026-01-01")   # breakeven leaves streak
    assert s.consecutive_losses == 0 and s.trades_today == 4
    assert s.realized_pnl_today == pytest.approx(-8.0)


def test_new_day_resets_counters():
    s = new_state(day="2026-01-01")
    s = register_result(s, -5, day="2026-01-01")
    s = register_result(s, -5, day="2026-01-02")  # new day
    assert s.day == "2026-01-02"
    assert s.trades_today == 1 and s.consecutive_losses == 1
    assert s.realized_pnl_today == pytest.approx(-5.0)


def test_daily_loss_cap_usd():
    assert daily_loss_cap_usd(PROFILE, 200) == pytest.approx(20.0)


def test_kill_switch_trips_on_streak():
    s = GuardState(day="2026-01-01", consecutive_losses=3)
    res = check_guards(PROFILE, s, account_equity=200)
    assert res["allowed"] is False
    assert res["checks"]["consecutive_losses"] is False


def test_max_trades_per_day_blocks():
    s = GuardState(day="2026-01-01", trades_today=5)
    res = check_guards(PROFILE, s, account_equity=200)
    assert res["allowed"] is False and res["checks"]["max_trades_per_day"] is False


def test_daily_loss_cap_blocks():
    s = GuardState(day="2026-01-01", realized_pnl_today=-25)
    res = check_guards(PROFILE, s, account_equity=200)  # cap = $20
    assert res["allowed"] is False and res["checks"]["daily_loss_cap"] is False


def test_all_clear_allowed():
    s = GuardState(day="2026-01-01", trades_today=1, realized_pnl_today=-3, consecutive_losses=1)
    res = check_guards(PROFILE, s, account_equity=200)
    assert res["allowed"] is True and all(res["checks"].values())


def test_guards_without_equity_skip_loss_cap():
    s = GuardState(day="2026-01-01", realized_pnl_today=-9999)
    res = check_guards(PROFILE, s)  # no equity, no explicit cap -> loss cap not checked
    assert "daily_loss_cap" not in res["checks"]
    assert res["allowed"] is True


def test_ev_gate_allows_positive_edge():
    g = ev_gate(PROFILE, 0.71, 0.80)
    assert g["allowed"] is True and g["edge"] == pytest.approx(0.09)


def test_ev_gate_blocks_insufficient_edge():
    # win_prob just above price but below price + min_edge(0.02)
    g = ev_gate(PROFILE, 0.71, 0.72)
    assert g["allowed"] is False
    assert g["required_win_prob"] == pytest.approx(0.73)


def test_config_profile_exposes_risk_controls():
    import polybtc_config as cfgmod
    prof = cfgmod.get_profile(cfgmod.load_config(), "conservative")
    assert prof["max_consecutive_losses"] == 3
    assert prof["min_edge"] == pytest.approx(0.02)
