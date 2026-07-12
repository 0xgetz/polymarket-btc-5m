"""Unit tests for PolyBTC Momentum config loader and preflight engine."""
import copy
import sys
from pathlib import Path

import pytest

# Make scripts/ importable.
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import polybtc_config as cfgmod  # noqa: E402
from polybtc_preflight import MarketSnapshot, evaluate, compute_hedge  # noqa: E402


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
    assert {"conservative", "aggressive", "high_confidence"} <= set(cfg["profiles"])


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
    base = dict(
        seconds_left=profile["entry_window_seconds_left_target"],
        btc_move_usd=profile["btc_move_usd_min"] + 10,
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
    assert d.stake_usd == min(conservative["stake_usd"], conservative["max_notional_usd"])
    assert all(d.checks.values())


def test_stake_capped_by_max_notional(cfg):
    prof = cfgmod.get_profile(cfg, "conservative")
    prof = dict(prof, stake_usd=999.0, max_notional_usd=8.0)
    d = evaluate(prof, _good_market(prof))
    assert d.ok and d.stake_usd == 8.0


def test_picks_stronger_side_when_both_qualify(conservative):
    # DOWN is stronger; move must be negative when require_move_aligned is on.
    m = _good_market(conservative, up_ask=0.72, dn_ask=0.80, btc_move_usd=-90)
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
    d = evaluate(conservative, _good_market(conservative, up_ask=0.97))
    assert d.ok and d.hedge is None
