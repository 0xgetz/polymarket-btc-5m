#!/usr/bin/env python3
"""
PolyBTC Momentum — strategy config loader & validator.

Loads ``config/polybtc_profiles.yaml`` and exposes a single, *flattened*
resolved profile (shared rules + strategy reference + per-profile settings)
so that runners, the preflight gate, and tests all read from one source of
truth instead of duplicating hardcoded defaults.

CLI:
    python scripts/polybtc_config.py --validate
    python scripts/polybtc_config.py --profile conservative --show
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

try:
    import yaml
except ImportError:  # pragma: no cover - friendly message only
    yaml = None


def default_config_path() -> str:
    """Repo-relative path to the canonical profiles file."""
    return str(Path(__file__).resolve().parents[1] / "config" / "polybtc_profiles.yaml")


def load_config(path: str | None = None) -> Dict[str, Any]:
    """Read and parse the YAML config. Raises a clear error if pyyaml is missing."""
    if yaml is None:
        raise RuntimeError(
            "pyyaml is required: install with `pip install pyyaml` "
            "(see requirements.txt)."
        )
    path = path or default_config_path()
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a mapping, got {type(data).__name__}")
    return data


def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_config(cfg: Dict[str, Any]) -> List[str]:
    """Return a list of human-readable validation errors. Empty list == valid."""
    errors: List[str] = []

    def require(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    # --- top-level sections ---
    for key in ("strategy_reference", "shared_rules", "profiles"):
        require(key in cfg, f"missing top-level section: '{key}'")
    if errors:
        return errors

    # --- strategy_reference ---
    sr = cfg.get("strategy_reference", {})
    require(
        _num(sr.get("entry_window_seconds_left_target"))
        and sr["entry_window_seconds_left_target"] > 0,
        "strategy_reference.entry_window_seconds_left_target must be a positive number",
    )
    require(
        _num(sr.get("entry_window_seconds_left_tolerance"))
        and sr["entry_window_seconds_left_tolerance"] >= 0,
        "strategy_reference.entry_window_seconds_left_tolerance must be >= 0",
    )
    require(
        _num(sr.get("btc_move_usd_min")) and sr["btc_move_usd_min"] > 0,
        "strategy_reference.btc_move_usd_min must be a positive number",
    )
    if _num(sr.get("btc_move_usd_min")) and _num(sr.get("btc_move_usd_max_reference")):
        require(
            sr["btc_move_usd_max_reference"] >= sr["btc_move_usd_min"],
            "strategy_reference.btc_move_usd_max_reference must be >= btc_move_usd_min",
        )

    # --- shared_rules ---
    rules = cfg.get("shared_rules", {})
    es = rules.get("execution_safety", {})
    require(
        _num(es.get("skip_if_quote_stale_sec_gt")) and es["skip_if_quote_stale_sec_gt"] > 0,
        "shared_rules.execution_safety.skip_if_quote_stale_sec_gt must be > 0",
    )
    require(
        _num(es.get("skip_if_spread_gt")) and 0 < es["skip_if_spread_gt"] < 1,
        "shared_rules.execution_safety.skip_if_spread_gt must be in (0, 1)",
    )
    require(
        _num(es.get("skip_if_top_ask_notional_usd_lt")) and es["skip_if_top_ask_notional_usd_lt"] >= 0,
        "shared_rules.execution_safety.skip_if_top_ask_notional_usd_lt must be >= 0",
    )
    st = rules.get("session_timing", {})
    require(
        _num(st.get("min_entry_seconds_left")) and st["min_entry_seconds_left"] > 0,
        "shared_rules.session_timing.min_entry_seconds_left must be > 0",
    )
    require(
        _num(st.get("exit_before_sec")) and st["exit_before_sec"] >= 0,
        "shared_rules.session_timing.exit_before_sec must be >= 0",
    )

    # --- profiles ---
    profiles = cfg.get("profiles", {})
    require(isinstance(profiles, dict) and len(profiles) >= 1, "profiles must be a non-empty mapping")
    for name in ("conservative", "aggressive"):
        require(name in profiles, f"missing expected profile: '{name}'")

    for pname, prof in (profiles or {}).items():
        if not isinstance(prof, dict):
            errors.append(f"profile '{pname}' must be a mapping")
            continue
        sig = prof.get("signal", {})
        require(
            _num(sig.get("threshold_price")) and 0 < sig["threshold_price"] < 1,
            f"profile '{pname}': signal.threshold_price must be in (0, 1)",
        )
        if "max_entry_price" in sig:
            require(
                _num(sig.get("max_entry_price")) and 0 < sig["max_entry_price"] <= 1,
                f"profile '{pname}': signal.max_entry_price must be in (0, 1]",
            )
            if _num(sig.get("threshold_price")) and _num(sig.get("max_entry_price")):
                require(
                    sig["max_entry_price"] >= sig["threshold_price"],
                    f"profile '{pname}': signal.max_entry_price must be >= threshold_price",
                )
        if "btc_move_usd_min" in sig:
            require(
                _num(sig.get("btc_move_usd_min")) and sig["btc_move_usd_min"] > 0,
                f"profile '{pname}': signal.btc_move_usd_min must be > 0",
            )
        if "btc_move_usd_max" in sig:
            require(
                _num(sig.get("btc_move_usd_max")) and sig["btc_move_usd_max"] > 0,
                f"profile '{pname}': signal.btc_move_usd_max must be > 0",
            )
            if _num(sig.get("btc_move_usd_min")) and _num(sig.get("btc_move_usd_max")):
                require(
                    sig["btc_move_usd_max"] >= sig["btc_move_usd_min"],
                    f"profile '{pname}': signal.btc_move_usd_max must be >= btc_move_usd_min",
                )
        if "min_skew_gap" in sig:
            require(
                _num(sig.get("min_skew_gap")) and 0 <= sig["min_skew_gap"] < 1,
                f"profile '{pname}': signal.min_skew_gap must be in [0, 1)",
            )
        if "confirm_polls" in sig:
            require(
                isinstance(sig.get("confirm_polls"), int)
                and not isinstance(sig.get("confirm_polls"), bool)
                and sig["confirm_polls"] >= 1,
                f"profile '{pname}': signal.confirm_polls must be an integer >= 1",
            )
        for flag in ("require_move_aligned", "require_entry_window", "require_1m_aligned"):
            if flag in sig:
                require(
                    isinstance(sig.get(flag), bool),
                    f"profile '{pname}': signal.{flag} must be a boolean",
                )
        sizing = prof.get("sizing", {})
        stake = sizing.get("stake_usd")
        maxn = sizing.get("max_notional_usd")
        require(_num(stake) and stake > 0, f"profile '{pname}': sizing.stake_usd must be > 0")
        require(_num(maxn) and maxn > 0, f"profile '{pname}': sizing.max_notional_usd must be > 0")
        if _num(stake) and _num(maxn):
            require(
                maxn >= stake,
                f"profile '{pname}': sizing.max_notional_usd must be >= stake_usd",
            )
        mode = sizing.get("stake_mode")
        if mode is not None:
            require(
                mode in ("fixed_or_cap", "edge_scaled"),
                f"profile '{pname}': sizing.stake_mode must be fixed_or_cap or edge_scaled",
            )
        es = sizing.get("edge_scale") or {}
        if es:
            for k in ("min_scale", "max_scale"):
                if k in es:
                    require(
                        _num(es.get(k)) and es[k] > 0,
                        f"profile '{pname}': sizing.edge_scale.{k} must be > 0",
                    )
            if _num(es.get("min_scale")) and _num(es.get("max_scale")):
                require(
                    es["max_scale"] >= es["min_scale"],
                    f"profile '{pname}': edge_scale.max_scale must be >= min_scale",
                )
            for k in ("edge_for_min_scale", "edge_for_full_scale"):
                if k in es:
                    require(
                        _num(es.get(k)) and 0 <= es[k] < 1,
                        f"profile '{pname}': sizing.edge_scale.{k} must be in [0,1)",
                    )
        lss = sizing.get("loss_streak_scale") or {}
        if lss:
            if "enabled" in lss:
                require(
                    isinstance(lss.get("enabled"), bool),
                    f"profile '{pname}': sizing.loss_streak_scale.enabled must be a boolean",
                )
            if "after_losses" in lss:
                require(
                    isinstance(lss.get("after_losses"), int)
                    and not isinstance(lss.get("after_losses"), bool)
                    and lss["after_losses"] >= 1,
                    f"profile '{pname}': loss_streak_scale.after_losses must be int >= 1",
                )
            if "scale_per_loss" in lss:
                require(
                    _num(lss.get("scale_per_loss")) and 0 < lss["scale_per_loss"] <= 1,
                    f"profile '{pname}': loss_streak_scale.scale_per_loss must be in (0,1]",
                )
            if "min_scale" in lss:
                require(
                    _num(lss.get("min_scale")) and 0 < lss["min_scale"] <= 1,
                    f"profile '{pname}': loss_streak_scale.min_scale must be in (0,1]",
                )
        dml = sizing.get("daily_max_loss_pct")
        require(_num(dml) and 0 < dml <= 100, f"profile '{pname}': sizing.daily_max_loss_pct must be in (0, 100]")
        mtd = sizing.get("max_trades_per_day")
        require(_num(mtd) and mtd >= 1, f"profile '{pname}': sizing.max_trades_per_day must be >= 1")

        hedge = prof.get("hedge", {})
        if hedge.get("enabled"):
            require(
                _num(hedge.get("trigger_side_price_gte")) and 0 < hedge["trigger_side_price_gte"] < 1,
                f"profile '{pname}': hedge.trigger_side_price_gte must be in (0, 1)",
            )
            hmin = hedge.get("hedge_notional_usd_min")
            hmax = hedge.get("hedge_notional_usd_max")
            require(_num(hmin) and hmin > 0, f"profile '{pname}': hedge.hedge_notional_usd_min must be > 0")
            require(_num(hmax) and hmax > 0, f"profile '{pname}': hedge.hedge_notional_usd_max must be > 0")
            if _num(hmin) and _num(hmax):
                require(hmax >= hmin, f"profile '{pname}': hedge_notional_usd_max must be >= min")

        sl = prof.get("stop_loss", {})
        if sl.get("enabled"):
            require(
                _num(sl.get("stop_loss_pct_from_entry")) and 0 < sl["stop_loss_pct_from_entry"] < 1,
                f"profile '{pname}': stop_loss.stop_loss_pct_from_entry must be in (0, 1)",
            )

        ep = prof.get("exit_policy", {})
        if ep:
            if "enabled" in ep:
                require(
                    isinstance(ep.get("enabled"), bool),
                    f"profile '{pname}': exit_policy.enabled must be a boolean",
                )
            hold = ep.get("hold_to_resolve") or {}
            if hold:
                if "min_bid" in hold:
                    require(
                        _num(hold.get("min_bid")) and 0 < hold["min_bid"] < 1,
                        f"profile '{pname}': exit_policy.hold_to_resolve.min_bid must be in (0,1)",
                    )
                if "max_seconds_left" in hold:
                    require(
                        _num(hold.get("max_seconds_left")) and hold["max_seconds_left"] >= 0,
                        f"profile '{pname}': exit_policy.hold_to_resolve.max_seconds_left must be >= 0",
                    )
                if "exit_before_sec" in hold:
                    require(
                        _num(hold.get("exit_before_sec")) and hold["exit_before_sec"] >= 0,
                        f"profile '{pname}': exit_policy.hold_to_resolve.exit_before_sec must be >= 0",
                    )
            early = ep.get("early_cut") or {}
            if early:
                if "max_seconds_left" in early:
                    require(
                        _num(early.get("max_seconds_left")) and early["max_seconds_left"] >= 0,
                        f"profile '{pname}': exit_policy.early_cut.max_seconds_left must be >= 0",
                    )
                if "min_adverse_from_entry" in early:
                    require(
                        _num(early.get("min_adverse_from_entry"))
                        and 0 <= early["min_adverse_from_entry"] < 1,
                        f"profile '{pname}': exit_policy.early_cut.min_adverse_from_entry must be in [0,1)",
                    )

        rc = prof.get("risk_controls", {})
        if rc:
            require(
                _num(rc.get("max_consecutive_losses")) and rc["max_consecutive_losses"] >= 1,
                f"profile '{pname}': risk_controls.max_consecutive_losses must be >= 1",
            )
            if "min_edge" in rc:
                require(
                    _num(rc.get("min_edge")) and 0 <= rc["min_edge"] < 1,
                    f"profile '{pname}': risk_controls.min_edge must be in [0, 1)",
                )
            if "require_ev_gate" in rc:
                require(
                    isinstance(rc.get("require_ev_gate"), bool),
                    f"profile '{pname}': risk_controls.require_ev_gate must be a boolean",
                )

        sf = prof.get("session_filter", {})
        if sf:
            if "enabled" in sf:
                require(
                    isinstance(sf.get("enabled"), bool),
                    f"profile '{pname}': session_filter.enabled must be a boolean",
                )
            if "require_hour" in sf:
                require(
                    isinstance(sf.get("require_hour"), bool),
                    f"profile '{pname}': session_filter.require_hour must be a boolean",
                )
            for key in ("allow_hours_utc", "block_hours_utc"):
                if key not in sf or sf.get(key) is None:
                    continue
                hours = sf.get(key)
                require(
                    isinstance(hours, list),
                    f"profile '{pname}': session_filter.{key} must be a list of hours",
                )
                if isinstance(hours, list):
                    for h in hours:
                        require(
                            isinstance(h, int)
                            and not isinstance(h, bool)
                            and 0 <= h <= 23,
                            f"profile '{pname}': session_filter.{key} entries must be ints 0-23",
                        )

    return errors


def get_profile(cfg: Dict[str, Any], name: str) -> Dict[str, Any]:
    """Return a flattened, resolved profile dict (shared rules + reference + profile)."""
    profiles = cfg.get("profiles", {})
    if name not in profiles:
        raise KeyError(f"unknown profile '{name}'; available: {sorted(profiles)}")
    prof = profiles[name]
    sr = cfg.get("strategy_reference", {})
    es = cfg.get("shared_rules", {}).get("execution_safety", {})
    st = cfg.get("shared_rules", {}).get("session_timing", {})

    sig = prof.get("signal", {})
    # Per-profile impulse / quality overrides fall back to strategy_reference.
    btc_min = sig.get("btc_move_usd_min", sr["btc_move_usd_min"])
    btc_max_ref = sig.get(
        "btc_move_usd_max_reference",
        sr.get("btc_move_usd_max_reference", sr["btc_move_usd_min"]),
    )
    # Hard max is optional; when unset, no upper impulse cap is applied.
    btc_max = sig.get("btc_move_usd_max")
    max_entry = sig.get("max_entry_price")
    min_skew = sig.get("min_skew_gap")
    confirm_polls = int(sig.get("confirm_polls", 1))
    rc = prof.get("risk_controls", {})
    sf = dict(prof.get("session_filter", {}) or {})
    return {
        "name": name,
        # signal / sizing
        "threshold_price": float(sig["threshold_price"]),
        "require_move_aligned": bool(sig.get("require_move_aligned", False)),
        "require_entry_window": bool(sig.get("require_entry_window", False)),
        "require_1m_aligned": bool(sig.get("require_1m_aligned", False)),
        "max_entry_price": float(max_entry) if max_entry is not None else None,
        "btc_move_usd_max": float(btc_max) if btc_max is not None else None,
        "min_skew_gap": float(min_skew) if min_skew is not None else None,
        "confirm_polls": max(1, confirm_polls),
        "stake_usd": float(prof["sizing"]["stake_usd"]),
        "stake_mode": str(prof["sizing"].get("stake_mode") or "fixed_or_cap"),
        "edge_scale": dict(prof["sizing"].get("edge_scale") or {}),
        "loss_streak_scale": dict(prof["sizing"].get("loss_streak_scale") or {}),
        "max_notional_usd": float(prof["sizing"]["max_notional_usd"]),
        "daily_max_loss_pct": float(prof["sizing"]["daily_max_loss_pct"]),
        "max_trades_per_day": int(prof["sizing"]["max_trades_per_day"]),
        "risk_per_trade_pct_equity": float(prof["sizing"].get("risk_per_trade_pct_equity", 0)),
        "max_consecutive_losses": int(rc.get("max_consecutive_losses", 3)),
        "min_edge": float(rc.get("min_edge", 0.0)),
        "require_ev_gate": bool(rc.get("require_ev_gate", False)),
        "session_filter": sf,
        "exit_policy": dict(prof.get("exit_policy", {}) or {}),
        "hedge": dict(prof.get("hedge", {})),
        "stop_loss": dict(prof.get("stop_loss", {})),
        # shared execution safety
        "skip_if_quote_stale_sec_gt": float(es["skip_if_quote_stale_sec_gt"]),
        "skip_if_spread_gt": float(es["skip_if_spread_gt"]),
        "skip_if_top_ask_notional_usd_lt": float(es["skip_if_top_ask_notional_usd_lt"]),
        "skip_if_dns_or_api_errors_consecutive": int(es.get("skip_if_dns_or_api_errors_consecutive", 3)),
        # session timing
        "min_entry_seconds_left": int(st["min_entry_seconds_left"]),
        "exit_before_sec": int(st["exit_before_sec"]),
        # strategy reference (profile signal may override impulse mins)
        "btc_move_usd_min": float(btc_min),
        "btc_move_usd_max_reference": float(btc_max_ref),
        "entry_window_seconds_left_target": int(sr["entry_window_seconds_left_target"]),
        "entry_window_seconds_left_tolerance": int(sr["entry_window_seconds_left_tolerance"]),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="PolyBTC Momentum config loader/validator")
    ap.add_argument("--config", default=None, help="path to polybtc_profiles.yaml")
    ap.add_argument("--validate", action="store_true", help="validate config and exit")
    ap.add_argument("--profile", default=None, help="resolve and show a flattened profile")
    ap.add_argument("--show", action="store_true", help="print resolved profile JSON")
    args = ap.parse_args()

    try:
        cfg = load_config(args.config)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    errors = validate_config(cfg)
    if args.validate or not args.profile:
        if errors:
            print("INVALID config:")
            for e in errors:
                print(f"  - {e}")
            return 1
        print(f"OK: config valid ({len(cfg.get('profiles', {}))} profiles: "
              f"{', '.join(sorted(cfg.get('profiles', {})))})")
        if not args.profile:
            return 0

    if args.profile:
        if errors:
            print("Refusing to resolve profile: config is invalid (run --validate).", file=sys.stderr)
            return 1
        resolved = get_profile(cfg, args.profile)
        print(json.dumps(resolved, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
