"""Tests for the accuracy-parameter calibrator."""

from polybtc_calibrate import apply_overrides, calibrate, score_result


def _base_profile():
    return {
        "threshold_price": 0.70,
        "stake_usd": 5.0,
        "max_notional_usd": 5.0,
        "min_entry_seconds_left": 60,
        "entry_window_seconds_left_target": 120,
        "entry_window_seconds_left_tolerance": 30,
        "btc_move_usd_min": 70,
        "btc_move_usd_max": None,
        "min_skew_gap": None,
        "require_move_aligned": False,
        "require_entry_window": False,
        "max_entry_price": None,
        "confirm_polls": 1,
        "skip_if_quote_stale_sec_gt": 3,
        "skip_if_spread_gt": 0.05,
        "skip_if_top_ask_notional_usd_lt": 25,
        "stop_loss": {"enabled": False},
        "hedge": {"enabled": False},
    }


def _rows():
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
            "btc_move_usd": "-92",
            "up_ask": "0.28",
            "dn_ask": "0.74",
            "spread": "0.02",
            "top_ask_notional_usd": "52",
            "quote_age_sec": "1",
            "outcome": "DOWN",
            "estimated_win_prob": "0.81",
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
        {
            "market_id": "m4",
            "timestamp": "2026-06-28T00:15:00Z",
            "seconds_left": "118",
            "btc_move_usd": "220",
            "up_ask": "0.80",
            "dn_ask": "0.22",
            "spread": "0.02",
            "top_ask_notional_usd": "50",
            "quote_age_sec": "1",
            "outcome": "DOWN",
            "estimated_win_prob": "0.70",
        },
    ]


def test_apply_overrides_clears_optional_caps():
    prof = apply_overrides(
        _base_profile(),
        {"btc_move_usd_max": None, "min_skew_gap": 0.18, "threshold_price": 0.75},
    )
    assert prof["btc_move_usd_max"] is None
    assert prof["min_skew_gap"] == 0.18
    assert prof["threshold_price"] == 0.75


def test_score_penalizes_below_min_trades():
    low = score_result(0, 1.0, 10.0, 2.0, 1.0, min_trades=2)
    high = score_result(3, 0.1, 1.0, 1.2, 0.6, min_trades=2)
    assert high > low


def test_calibrate_returns_ranked_best():
    report = calibrate(
        _base_profile(),
        _rows(),
        thresholds=[0.70, 0.80],
        skew_gaps=[None, 0.18],
        move_mins=[70.0],
        move_maxs=[None, 200.0],
        confirm_polls=[1],
        require_aligned=[True],
        min_trades=1,
        top=5,
    )
    assert report["grid_size"] == 8  # 2*2*1*2*1*1
    assert report["best"] is not None
    assert "params" in report["best"]
    assert len(report["top"]) <= 5
    # Best should be among the highest scores
    scores = [c["score"] for c in report["top"]]
    assert scores == sorted(scores, reverse=True)
