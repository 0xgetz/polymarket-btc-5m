"""Tests for the daily summary aggregator."""
import datetime as dt

import pytest

from polybtc_daily_summary import filter_by_date, build_summary, render_text


def _ts(date_iso, hour=12):
    d = dt.datetime.fromisoformat(date_iso).replace(hour=hour, tzinfo=dt.timezone.utc)
    return d.timestamp()


def _trades_for(date_iso, pnls):
    return [{"pnl": p, "side": "UP", "ts": _ts(date_iso, 10 + i)} for i, p in enumerate(pnls)]


def test_filter_by_date():
    trades = _trades_for("2026-01-01", [1, -1]) + _trades_for("2026-01-02", [2])
    day1 = filter_by_date(trades, "2026-01-01")
    assert len(day1) == 2
    assert len(filter_by_date(trades, "2026-01-02")) == 1
    assert filter_by_date(trades, "2026-01-03") == []


def test_build_summary_numbers():
    trades = _trades_for("2026-01-01", [2.0, 2.0, -5.0])
    out = build_summary(trades, "2026-01-01")
    assert out["date"] == "2026-01-01"
    assert out["stats"]["n_trades"] == 3
    assert out["stats"]["net_pnl"] == pytest.approx(-1.0)


def test_risk_flags_kill_switch_and_loss_cap():
    profile = {"max_consecutive_losses": 3, "daily_max_loss_pct": 10}
    trades = _trades_for("2026-01-01", [-5, -5, -5])  # 3-loss streak, net -15
    out = build_summary(trades, "2026-01-01", profile=profile, equity=100)
    assert out["risk"]["kill_switch_would_trip"] is True
    # cap = 100 * 10% = 10; net -15 <= -10 -> hit
    assert out["risk"]["daily_loss_cap_usd"] == pytest.approx(10.0)
    assert out["risk"]["daily_loss_cap_hit"] is True


def test_risk_flags_within_limits():
    profile = {"max_consecutive_losses": 3, "daily_max_loss_pct": 10}
    trades = _trades_for("2026-01-01", [2, -5, 2])
    out = build_summary(trades, "2026-01-01", profile=profile, equity=100)
    assert out["risk"]["kill_switch_would_trip"] is False
    assert out["risk"]["daily_loss_cap_hit"] is False


def test_render_text_has_key_fields():
    trades = _trades_for("2026-01-01", [2.0, -5.0])
    text = render_text(build_summary(trades, "2026-01-01"))
    assert "Daily Summary (2026-01-01" in text
    assert "Net PnL" in text and "Win-rate" in text


def test_render_text_empty_day():
    text = render_text(build_summary([], "2026-01-01"))
    assert "No settled trades" in text
