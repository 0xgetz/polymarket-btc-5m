"""Unit tests for PolyBTC Momentum config loader and preflight engine."""
import copy
import sys
from pathlib import Path

import pytest

# Make scripts/ importable.
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import polybtc_config as cfgmod  # noqa: E402
from polybtc_preflight import (  # noqa: E402
    MarketSnapshot,
    evaluate,
    compute_hedge,
    estimate_win_prob,
    scale_stake_usd,
    session_hour_allowed,
)


@pytest.fixture(scope="module")
def cfg():
    return cfgmod.load_config()


@pytest.fixture(scope="module")
def conservative(cfg):
    return cfgmod.get_profile(cfg, "conservative")


# --------------------------------------------------------------------------- #
# config loader / validator
# --------------------------------------------------------------------------- #
def test_shipped_config_is_valid(cfg):
    assert cfgmod.validate_config(cfg) == []


def test_expected_profiles_present(cfg):
    assert {
        "conservative",
        "aggressive",
        "high_confidence",
        "observe",
        "micro_10",
    } <= set(cfg["profiles"])


def test_get_profile_flattens_fields(conservative):
    for key in (
        "threshold_price", "stake_usd", "max_notional_usd",
        "min_entry_seconds_left", "exit_before_sec",
        "btc_move_usd_min", "skip_if_spread_gt",
    ):
        assert key in conservative
    assert 0 < conservative["threshold_price"] < 1


def test_get_profile_unknown_raises(cfg):
    with pytest.raises(KeyError):
        cfgmod.get_profile(cfg, "does-not-exist")


def test_validator_catches_bad_threshold(cfg):
    bad = copy.deepcopy(cfg)
    bad["profiles"]["conservative"]["signal"]["threshold_price"] = 1.5
    errs = cfgmod.validate_config(bad)
    assert any("threshold_price" in e for e in errs)


def test_validator_catches_notional_below_stake(cfg):
    bad = copy.deepcopy(cfg)
    bad["profiles"]["conservative"]["sizing"]["max_notional_usd"] = 1
    bad["profiles"]["conservative"]["sizing"]["stake_usd"] = 9
    errs = cfgmod.validate_config(bad)
    assert any("max_notional_usd must be >= stake_usd" in e for e in errs)


def test_validator_catches_missing_section():
    errs = cfgmod.validate_config({"profiles": {}})
    assert any("strategy_reference" in e for e in errs)


# --------------------------------------------------------------------------- #
# preflight engine
# --------------------------------------------------------------------------- #
def _good_market(profile, **overrides):
    move = overrides.get("btc_move_usd", profile["btc_move_usd_min"] + 10)
    # Default 1m aligned with 5m so require_1m_aligned profiles still GO in unit tests.
    if "btc_move_1m_usd" not in overrides:
        overrides = dict(overrides)
        overrides["btc_move_1m_usd"] = 5.0 if float(move) >= 0 else -5.0
    if "hour_utc" not in overrides:
        overrides = dict(overrides)
        overrides.setdefault("hour_utc", 14)
    base = dict(
        seconds_left=profile["entry_window_seconds_left_target"],
        btc_move_usd=move,
        up_ask=max(0.71, profile["threshold_price"]),
        dn_ask=0.29,
        spread=profile["skip_if_spread_gt"] / 2,
        top_ask_notional_usd=profile["skip_if_top_ask_notional_usd_lt"] + 10,
        quote_age_sec=1.0,
    )
    base.update(overrides)
    return MarketSnapshot(**base)


def test_go_decision_picks_up(conservative):
    d = evaluate(conservative, _good_market(conservative))
    assert d.ok is True
    assert d.side == "UP"
    # Edge-scaled profiles may size above base stake (still ≤ max_notional).
    assert d.stake_usd is not None
    assert 0 < d.stake_usd <= conservative["max_notional_usd"]
    assert all(d.checks.values())


def test_stake_capped_by_max_notional(cfg):
    prof = cfgmod.get_profile(cfg, "conservative")
    prof = dict(prof, stake_usd=999.0, max_notional_usd=8.0)
    d = evaluate(prof, _good_market(prof))
    assert d.ok and d.stake_usd == 8.0


def test_picks_stronger_side_when_both_qualify(conservative):
    # DOWN is stronger; move must be negative when require_move_aligned is on.
    # Skew gap must clear profile min_skew_gap (chosen - opposite).
    m = _good_market(
        conservative, up_ask=0.55, dn_ask=0.80, btc_move_usd=-90, btc_move_1m_usd=-8
    )
    d = evaluate(conservative, m)
    assert d.ok and d.side == "DOWN" and d.entry_price == 0.80


def test_blocks_misaligned_impulse(conservative):
    # Positive BTC move but DOWN is the only side over threshold → blocked.
    m = _good_market(conservative, up_ask=0.40, dn_ask=0.80, btc_move_usd=90)
    d = evaluate(conservative, m)
    assert d.ok is False
    assert d.checks.get("move_aligned") is False


def test_max_entry_price_blocks_rich_asks(cfg):
    prof = cfgmod.get_profile(cfg, "high_confidence")
    m = _good_market(
        prof,
        up_ask=0.97,
        dn_ask=0.05,
        btc_move_usd=prof["btc_move_usd_min"] + 5,
        seconds_left=prof["entry_window_seconds_left_target"],
    )
    d = evaluate(prof, m)
    assert d.ok is False
    assert d.checks["threshold_side"] is False


def test_high_confidence_go_in_window(cfg):
    prof = cfgmod.get_profile(cfg, "high_confidence")
    m = _good_market(
        prof,
        up_ask=0.86,
        dn_ask=0.16,
        btc_move_usd=prof["btc_move_usd_min"] + 10,
        seconds_left=prof["entry_window_seconds_left_target"],
    )
    d = evaluate(prof, m)
    assert d.ok is True
    assert d.side == "UP"
    assert d.checks.get("move_aligned") is True
    assert d.checks.get("entry_window") is True
    assert d.checks.get("skew_confirm") is True
    assert d.checks.get("impulse_max") is True


def test_blocks_blowoff_impulse(conservative):
    max_move = conservative.get("btc_move_usd_max")
    if max_move is None:
        pytest.skip("btc_move_usd_max not set")
    m = _good_market(conservative, btc_move_usd=float(max_move) + 50)
    d = evaluate(conservative, m)
    assert d.ok is False
    assert d.checks.get("impulse_max") is False


def test_blocks_weak_skew(conservative):
    # UP clears threshold but gap vs DOWN is thin (crowd not committed).
    m = _good_market(conservative, up_ask=0.72, dn_ask=0.68, btc_move_usd=90)
    d = evaluate(conservative, m)
    assert d.ok is False
    assert d.checks.get("skew_confirm") is False


def test_confirm_tracker_requires_streak():
    from polybtc_preflight import ConfirmTracker, Decision

    tr = ConfirmTracker(needed=3)
    go_up = Decision(
        ok=True, side="UP", entry_price=0.8, stake_usd=5, max_notional_usd=8,
        stop_loss_price=None, hedge=None,
    )
    nogo = Decision(
        ok=False, side=None, entry_price=None, stake_usd=None,
        max_notional_usd=None, stop_loss_price=None, hedge=None,
    )
    assert tr.update(go_up) == (False, 1)
    assert tr.update(go_up) == (False, 2)
    assert tr.update(go_up) == (True, 3)
    # Reset on NO-GO
    assert tr.update(nogo) == (False, 0)
    # Side flip restarts streak
    go_dn = Decision(
        ok=True, side="DOWN", entry_price=0.8, stake_usd=5, max_notional_usd=8,
        stop_loss_price=None, hedge=None,
    )
    assert tr.update(go_up) == (False, 1)
    assert tr.update(go_dn) == (False, 1)
    assert tr.update(go_dn) == (False, 2)
    assert tr.update(go_dn) == (True, 3)


def test_profile_exposes_accuracy_filters(cfg):
    prof = cfgmod.get_profile(cfg, "conservative")
    assert prof.get("min_skew_gap") is not None
    assert prof.get("confirm_polls", 1) >= 1
    assert prof.get("btc_move_usd_max") is not None
    assert "require_ev_gate" in prof
    assert "session_filter" in prof


def test_estimate_win_prob_rewards_strong_setup():
    weak = estimate_win_prob(
        entry_price=0.80,
        abs_move_usd=70,
        move_min_usd=70,
        skew_gap=0.05,
        in_target_window=False,
        seconds_left=200,
    )
    strong = estimate_win_prob(
        entry_price=0.80,
        abs_move_usd=140,
        move_min_usd=70,
        skew_gap=0.40,
        in_target_window=True,
        seconds_left=120,
    )
    assert strong > weak
    assert strong > 0.80  # positive estimated edge on strong setup


def test_ev_gate_blocks_thin_edge(conservative):
    prof = dict(conservative, require_ev_gate=True, min_edge=0.20)
    # Strong enough to pass other filters but not a +20pp heuristic edge.
    m = _good_market(conservative, up_ask=0.74, dn_ask=0.28, btc_move_usd=80, hour_utc=14)
    d = evaluate(prof, m)
    assert d.ok is False
    assert d.checks.get("ev_gate") is False
    assert d.edge is not None and d.edge < 0.20


def test_ev_gate_passes_good_setup(conservative):
    prof = dict(conservative, require_ev_gate=True, min_edge=0.02)
    m = _good_market(
        conservative,
        up_ask=0.72,
        dn_ask=0.28,
        btc_move_usd=120,
        hour_utc=14,
    )
    d = evaluate(prof, m)
    assert d.ok is True
    assert d.checks.get("ev_gate") is True
    assert d.estimated_win_prob is not None
    assert d.edge is not None and d.edge >= 0.02


def test_session_filter_blocks_listed_hours(conservative):
    prof = dict(
        conservative,
        session_filter={
            "enabled": True,
            "require_hour": True,
            "block_hours_utc": [3, 4],
            "allow_hours_utc": None,
        },
    )
    m = _good_market(conservative, hour_utc=3)
    d = evaluate(prof, m)
    assert d.ok is False
    assert d.checks.get("session_hour") is False


def test_session_filter_allowlist(conservative):
    ok, _ = session_hour_allowed(
        {"session_filter": {"enabled": True, "allow_hours_utc": [12, 13], "block_hours_utc": []}},
        12,
    )
    bad, reason = session_hour_allowed(
        {"session_filter": {"enabled": True, "allow_hours_utc": [12, 13], "block_hours_utc": []}},
        9,
    )
    assert ok is True
    assert bad is False
    assert "allow_hours_utc" in reason


def test_1m_align_blocks_wick(conservative):
    prof = dict(conservative, require_1m_aligned=True)
    # 5m up but 1m already reversing down → block.
    m = _good_market(prof, btc_move_usd=90, btc_move_1m_usd=-12, hour_utc=14)
    d = evaluate(prof, m)
    assert d.ok is False
    assert d.checks.get("move_1m_aligned") is False


def test_1m_align_passes_when_same_sign(conservative):
    prof = dict(conservative, require_1m_aligned=True)
    m = _good_market(prof, btc_move_usd=90, btc_move_1m_usd=8, hour_utc=14)
    d = evaluate(prof, m)
    assert d.ok is True
    assert d.checks.get("move_1m_aligned") is True


def test_edge_scaled_stake_increases_with_edge():
    low, s_lo, st_lo = scale_stake_usd(
        base_stake=5,
        max_notional=10,
        edge=0.02,
        min_edge=0.02,
        sizing={
            "stake_mode": "edge_scaled",
            "edge_scale": {
                "enabled": True,
                "min_scale": 0.5,
                "max_scale": 1.25,
                "edge_for_min_scale": 0.02,
                "edge_for_full_scale": 0.06,
            },
        },
    )
    high, s_hi, st_hi = scale_stake_usd(
        base_stake=5,
        max_notional=10,
        edge=0.06,
        min_edge=0.02,
        sizing={
            "stake_mode": "edge_scaled",
            "edge_scale": {
                "enabled": True,
                "min_scale": 0.5,
                "max_scale": 1.25,
                "edge_for_min_scale": 0.02,
                "edge_for_full_scale": 0.06,
            },
        },
    )
    assert s_lo == 0.5 and abs(low - 2.5) < 1e-9
    assert s_hi == 1.25 and abs(high - 6.25) < 1e-9
    assert high > low
    assert st_lo == 1.0 and st_hi == 1.0


def test_loss_streak_soft_size():
    from polybtc_preflight import loss_streak_scale

    pol = {"enabled": True, "after_losses": 1, "scale_per_loss": 0.5, "min_scale": 0.25}
    assert loss_streak_scale(consecutive_losses=0, policy=pol) == 1.0
    assert loss_streak_scale(consecutive_losses=1, policy=pol) == 0.5
    assert loss_streak_scale(consecutive_losses=2, policy=pol) == 0.25
    stake, _, streak = scale_stake_usd(
        base_stake=8,
        max_notional=8,
        edge=None,
        min_edge=0.02,
        sizing={"stake_mode": "fixed_or_cap", "loss_streak_scale": pol},
        consecutive_losses=1,
    )
    assert streak == 0.5
    assert abs(stake - 4.0) < 1e-9


def test_observe_profile_loads(cfg):
    prof = cfgmod.get_profile(cfg, "observe")
    assert prof["btc_move_usd_min"] <= 40
    assert prof["require_ev_gate"] is False
    assert prof["threshold_price"] <= 0.60


def test_micro_10_profile_caps(cfg):
    prof = cfgmod.get_profile(cfg, "micro_10")
    assert prof["stake_usd"] == 1.0
    assert prof["max_notional_usd"] == 1.0
    assert prof["max_trades_per_day"] <= 5
    assert prof["max_consecutive_losses"] <= 2
    assert prof["hedge"].get("enabled") is False


def test_nogo_on_thin_liquidity(conservative):
    m = _good_market(conservative, top_ask_notional_usd=1.0)
    d = evaluate(conservative, m)
    assert d.ok is False and d.checks["liquidity"] is False
    assert d.side is None


def test_nogo_on_wide_spread(conservative):
    m = _good_market(conservative, spread=0.99)
    d = evaluate(conservative, m)
    assert not d.ok and d.checks["spread"] is False


def test_nogo_on_small_move(conservative):
    m = _good_market(conservative, btc_move_usd=5)
    d = evaluate(conservative, m)
    assert not d.ok and d.checks["impulse_move"] is False


def test_nogo_on_too_little_time(conservative):
    m = _good_market(conservative, seconds_left=1)
    d = evaluate(conservative, m)
    assert not d.ok and d.checks["time_to_close"] is False


def test_nogo_on_stale_quote(conservative):
    m = _good_market(conservative, quote_age_sec=999)
    d = evaluate(conservative, m)
    assert not d.ok and d.checks["quote_fresh"] is False


def test_nogo_when_no_side_over_threshold(conservative):
    m = _good_market(conservative, up_ask=0.40, dn_ask=0.41)
    d = evaluate(conservative, m)
    assert not d.ok and d.checks["threshold_side"] is False


def test_stop_loss_price_computed(conservative):
    d = evaluate(conservative, _good_market(conservative, up_ask=0.80))
    if conservative["stop_loss"].get("enabled"):
        pct = conservative["stop_loss"]["stop_loss_pct_from_entry"]
        assert d.stop_loss_price == round(0.80 * (1 - pct), 4)


def test_hedge_arms_on_extreme_skew(conservative):
    # Hedge is a near-close action evaluated independently of the entry gate.
    h = conservative["hedge"]
    if not h.get("enabled"):
        pytest.skip("hedge disabled in profile")
    sl = h["trigger_seconds_left_lte"] - 1  # inside the hedge time window
    plan = compute_hedge(conservative, "UP", max(h["trigger_side_price_gte"], 0.96), sl)
    assert plan is not None
    assert plan["side"] == "DOWN"
    assert h["hedge_notional_usd_min"] <= plan["notional_usd"] <= h["hedge_notional_usd_max"]


def test_no_hedge_when_price_below_trigger(conservative):
    h = conservative["hedge"]
    sl = h.get("trigger_seconds_left_lte", 40) - 1
    assert compute_hedge(conservative, "UP", 0.71, sl) is None


def test_no_hedge_outside_time_window(conservative):
    h = conservative["hedge"]
    if not h.get("enabled"):
        pytest.skip("hedge disabled in profile")
    sl = h["trigger_seconds_left_lte"] + 30  # too early for a hedge
    assert compute_hedge(conservative, "UP", 0.97, sl) is None


def test_entry_decision_has_no_hedge_in_entry_window(conservative):
    # At a normal entry (well before close) the entry Decision carries no hedge.
    # Keep price below "ultra-rich" so EV gate still clears.
    d = evaluate(
        conservative,
        _good_market(conservative, up_ask=0.80, dn_ask=0.22, btc_move_usd=110, hour_utc=14),
    )
    assert d.ok and d.hedge is None
