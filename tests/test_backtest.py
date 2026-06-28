"""Tests for the CSV historical backtester."""

import pytest

from polybtc_backtest import run_backtest


@pytest.fixture
def profile():
    return {
        "threshold_price": 0.70,
        "stake_usd": 5.0,
        "max_notional_usd": 5.0,
        "min_entry_seconds_left": 60,
        "entry_window_seconds_left_target": 120,
        "entry_window_seconds_left_tolerance": 30,
        "btc_move_usd_min": 70,
        "skip_if_quote_stale_sec_gt": 3,
        "skip_if_spread_gt": 0.05,
        "skip_if_top_ask_notional_usd_lt": 25,
        "stop_loss": {"enabled": False},
        "hedge": {"enabled": False},
    }


@pytest.fixture
def rows():
    return [
        {
            "market_id": "m1",
            "timestamp": "2026-06-28T00:00:00Z",
            "seconds_left": "118",
            "btc_move_usd": "84",
            "up_ask": "0.71",
            "dn_ask": "0.30",
            "spread": "0.02",
            "top_ask_notional_usd": "45",
            "quote_age_sec": "1",
            "outcome": "UP",
            "estimated_win_prob": "0.79",
        },
        {
            "market_id": "m2",
            "timestamp": "2026-06-28T00:05:00Z",
            "seconds_left": "121",
            "btc_move_usd": "92",
            "up_ask": "0.28",
            "dn_ask": "0.74",
            "spread": "0.02",
            "top_ask_notional_usd": "52",
            "quote_age_sec": "1",
            "outcome": "UP",
            "estimated_win_prob": "0.75",
        },
        {
            "market_id": "m3",
            "timestamp": "2026-06-28T00:10:00Z",
            "seconds_left": "119",
            "btc_move_usd": "40",
            "up_ask": "0.72",
            "dn_ask": "0.29",
            "spread": "0.02",
            "top_ask_notional_usd": "49",
            "quote_age_sec": "1",
            "outcome": "UP",
            "estimated_win_prob": "0.80",
        },
    ]


def test_backtest_replays_only_preflight_signals(profile, rows):
    result = run_backtest(profile, rows)

    assert result.rows == 3
    assert result.signals == 2
    assert result.trades == 2
    assert result.wins == 1
    assert result.losses == 1
    assert result.win_rate == pytest.approx(0.5)
    assert result.net_pnl_usd == pytest.approx(round((5 * 0.29 / 0.71) - 5, 4))
    assert result.by_side["UP"]["trades"] == 1.0
    assert result.by_side["DOWN"]["trades"] == 1.0


def test_ev_gate_skips_low_edge_trades(profile, rows):
    result = run_backtest(profile, rows, ev_gate=True, min_edge=0.05)

    assert result.signals == 2
    assert result.skipped_ev == 1
    assert result.trades == 1
    assert result.wins == 1
    assert result.net_pnl_usd > 0
    assert result.avg_edge == pytest.approx(0.08)


def test_win_loss_outcome_aliases(profile):
    result = run_backtest(
        profile,
        [
            {
                "market_id": "m1",
                "timestamp": "",
                "seconds_left": "118",
                "btc_move_usd": "84",
                "up_ask": "0.71",
                "dn_ask": "0.30",
                "spread": "0.02",
                "top_ask_notional_usd": "45",
                "quote_age_sec": "1",
                "outcome": "win",
            },
            {
                "market_id": "m2",
                "timestamp": "",
                "seconds_left": "118",
                "btc_move_usd": "84",
                "up_ask": "0.71",
                "dn_ask": "0.30",
                "spread": "0.02",
                "top_ask_notional_usd": "45",
                "quote_age_sec": "1",
                "outcome": "loss",
            },
        ],
    )

    assert result.trades == 2
    assert result.wins == 1
    assert result.losses == 1
