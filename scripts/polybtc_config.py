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

    return {
        "name": name,
        # signal / sizing
        "threshold_price": float(prof["signal"]["threshold_price"]),
        "stake_usd": float(prof["sizing"]["stake_usd"]),
        "max_notional_usd": float(prof["sizing"]["max_notional_usd"]),
        "daily_max_loss_pct": float(prof["sizing"]["daily_max_loss_pct"]),
        "max_trades_per_day": int(prof["sizing"]["max_trades_per_day"]),
        "risk_per_trade_pct_equity": float(prof["sizing"].get("risk_per_trade_pct_equity", 0)),
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
        # strategy reference
        "btc_move_usd_min": float(sr["btc_move_usd_min"]),
        "btc_move_usd_max_reference": float(sr.get("btc_move_usd_max_reference", sr["btc_move_usd_min"])),
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
        if args.show or True:
            print(json.dumps(resolved, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
