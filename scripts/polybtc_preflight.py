#!/usr/bin/env python3
"""
PolyBTC Momentum — preflight decision engine.

A pure-logic implementation of the README "Execution Checklist". Given a
resolved profile (from ``polybtc_config.get_profile``) and a snapshot of the
current market, it returns a structured GO / NO-GO decision: chosen side,
recommended stake, optional micro-hedge, stop-loss price, and per-check
pass/fail reasons.

This contains no network or order-placement logic, so it is fully
deterministic and unit-testable. Runners can import ``evaluate`` to gate live
orders; operators can run it as a CLI for manual dry-run checks.

CLI:
    python scripts/polybtc_preflight.py --profile conservative \\
        --seconds-left 118 --btc-move-usd 84 --up-ask 0.71 --dn-ask 0.29 \\
        --spread 0.02 --top-ask-notional 41 --quote-age-sec 1
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class MarketSnapshot:
    seconds_left: float          # seconds remaining in the active 5m slot
    btc_move_usd: float          # observed BTC move in the active interval (abs $)
    up_ask: Optional[float]      # CLOB best ask for UP token (0..1), None if unavailable
    dn_ask: Optional[float]      # CLOB best ask for DOWN token (0..1), None if unavailable
    spread: float                # top-of-book spread of the picked side
    top_ask_notional_usd: float  # notional available at top ask ($)
    quote_age_sec: float = 0.0   # age of the latest quote (staleness)


@dataclass
class Decision:
    ok: bool                                   # True only if all hard checks pass
    side: Optional[str]                        # 'UP' | 'DOWN' | None
    entry_price: Optional[float]               # ask used for entry
    stake_usd: Optional[float]                 # recommended stake (capped)
    max_notional_usd: Optional[float]          # profile notional cap
    stop_loss_price: Optional[float]           # computed stop price (if enabled)
    hedge: Optional[Dict[str, Any]]            # hedge plan or None
    checks: Dict[str, bool] = field(default_factory=dict)   # per-check pass/fail
    reasons: List[str] = field(default_factory=list)        # human-readable notes
    in_target_window: bool = False             # soft: within ideal ~target window


def _round(x: Optional[float], n: int = 4) -> Optional[float]:
    return None if x is None else round(float(x), n)


def compute_hedge(
    profile: Dict[str, Any],
    side: Optional[str],
    entry_price: Optional[float],
    seconds_left: float,
    stake_usd: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Decide an optional micro-hedge for the near-close window.

    The hedge is a last-seconds tail-risk reducer evaluated *independently* of
    the entry-time gate: it fires only when skew on the held side is extreme
    (>= ``trigger_side_price_gte``) and we are inside the hedge time window
    (``seconds_left <= trigger_seconds_left_lte``). Returns a plan or None.
    """
    hedge = profile.get("hedge", {})
    if not hedge.get("enabled") or side is None or entry_price is None:
        return None
    if entry_price < float(hedge.get("trigger_side_price_gte", 2)):
        return None
    if seconds_left > float(hedge.get("trigger_seconds_left_lte", -1)):
        return None
    base = stake_usd if stake_usd is not None else float(profile["stake_usd"])
    share = float(hedge.get("hedge_share_of_main_pct", 0)) / 100.0
    raw = base * share
    hmin = float(hedge.get("hedge_notional_usd_min", 0))
    hmax = float(hedge.get("hedge_notional_usd_max", raw))
    notional = min(max(raw, hmin), hmax)
    return {
        "side": "DOWN" if side == "UP" else "UP",
        "notional_usd": _round(notional, 2),
        "reason": "extreme skew tail-risk hedge",
    }


def evaluate(profile: Dict[str, Any], market: MarketSnapshot) -> Decision:
    """Run all hard guards + side selection and return a Decision."""
    checks: Dict[str, bool] = {}
    reasons: List[str] = []

    # 1) Time-to-close: must have enough seconds left to safely enter.
    min_left = profile["min_entry_seconds_left"]
    ok_time = market.seconds_left >= min_left
    checks["time_to_close"] = ok_time
    if not ok_time:
        reasons.append(f"seconds_left {market.seconds_left:.0f} < min_entry {min_left}")

    # Soft: are we inside the ideal entry window (target +/- tolerance)?
    tgt = profile["entry_window_seconds_left_target"]
    tol = profile["entry_window_seconds_left_tolerance"]
    in_window = (tgt - tol) <= market.seconds_left <= (tgt + tol)

    # 2) Impulse confirmation: BTC move meets minimum.
    move_min = profile["btc_move_usd_min"]
    ok_move = abs(market.btc_move_usd) >= move_min
    checks["impulse_move"] = ok_move
    if not ok_move:
        reasons.append(f"btc_move ${abs(market.btc_move_usd):.0f} < min ${move_min:.0f}")

    # 3) Quote freshness.
    ok_fresh = market.quote_age_sec <= profile["skip_if_quote_stale_sec_gt"]
    checks["quote_fresh"] = ok_fresh
    if not ok_fresh:
        reasons.append(
            f"quote_age {market.quote_age_sec:.1f}s > "
            f"{profile['skip_if_quote_stale_sec_gt']:.1f}s"
        )

    # 4) Spread guard.
    ok_spread = market.spread <= profile["skip_if_spread_gt"]
    checks["spread"] = ok_spread
    if not ok_spread:
        reasons.append(f"spread {market.spread:.3f} > max {profile['skip_if_spread_gt']:.3f}")

    # 5) Liquidity guard.
    ok_liq = market.top_ask_notional_usd >= profile["skip_if_top_ask_notional_usd_lt"]
    checks["liquidity"] = ok_liq
    if not ok_liq:
        reasons.append(
            f"top_ask_notional ${market.top_ask_notional_usd:.0f} < "
            f"min ${profile['skip_if_top_ask_notional_usd_lt']:.0f}"
        )

    # 6) Side selection (momentum): pick the side whose ask >= threshold; if
    #    both qualify, take the stronger (higher ask).
    thr = profile["threshold_price"]
    candidates = []
    if market.up_ask is not None and market.up_ask >= thr:
        candidates.append(("UP", float(market.up_ask)))
    if market.dn_ask is not None and market.dn_ask >= thr:
        candidates.append(("DOWN", float(market.dn_ask)))
    side: Optional[str] = None
    entry_price: Optional[float] = None
    if candidates:
        side, entry_price = max(candidates, key=lambda c: c[1])
    ok_side = side is not None
    checks["threshold_side"] = ok_side
    if not ok_side:
        ua = "n/a" if market.up_ask is None else f"{market.up_ask:.2f}"
        da = "n/a" if market.dn_ask is None else f"{market.dn_ask:.2f}"
        reasons.append(f"no side >= threshold {thr:.2f} (UP {ua}, DOWN {da})")

    # --- aggregate ---
    ok = all(checks.values())

    stake_usd: Optional[float] = None
    max_notional: Optional[float] = None
    stop_price: Optional[float] = None
    hedge_plan: Optional[Dict[str, Any]] = None

    if ok:
        max_notional = profile["max_notional_usd"]
        stake_usd = min(profile["stake_usd"], max_notional)

        sl = profile.get("stop_loss", {})
        if sl.get("enabled") and entry_price is not None:
            stop_price = entry_price * (1.0 - float(sl["stop_loss_pct_from_entry"]))

        hedge_plan = compute_hedge(profile, side, entry_price, market.seconds_left, stake_usd)
        if hedge_plan:
            reasons.append(
                f"hedge armed: ${hedge_plan['notional_usd']} on {hedge_plan['side']}"
            )

    if ok:
        reasons.insert(0, f"GO: enter {side} @ {entry_price:.2f} stake ${stake_usd:g}")

    return Decision(
        ok=ok,
        side=side if ok else None,
        entry_price=_round(entry_price) if ok else None,
        stake_usd=_round(stake_usd, 2),
        max_notional_usd=_round(max_notional, 2),
        stop_loss_price=_round(stop_price),
        hedge=hedge_plan,
        checks=checks,
        reasons=reasons,
        in_target_window=in_window,
    )


def main() -> int:
    # Local import so the engine stays importable even without pyyaml present.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from polybtc_config import load_config, validate_config, get_profile  # noqa: E402

    ap = argparse.ArgumentParser(description="PolyBTC Momentum preflight gate")
    ap.add_argument("--config", default=None)
    ap.add_argument("--profile", default="conservative")
    ap.add_argument("--seconds-left", type=float, required=True)
    ap.add_argument("--btc-move-usd", type=float, required=True)
    ap.add_argument("--up-ask", type=float, default=None)
    ap.add_argument("--dn-ask", type=float, default=None)
    ap.add_argument("--spread", type=float, default=0.0)
    ap.add_argument("--top-ask-notional", type=float, default=0.0)
    ap.add_argument("--quote-age-sec", type=float, default=0.0)
    args = ap.parse_args()

    cfg = load_config(args.config)
    errs = validate_config(cfg)
    if errs:
        print("ERROR: invalid config:", *(f"\n  - {e}" for e in errs), file=sys.stderr)
        return 2
    profile = get_profile(cfg, args.profile)

    market = MarketSnapshot(
        seconds_left=args.seconds_left,
        btc_move_usd=args.btc_move_usd,
        up_ask=args.up_ask,
        dn_ask=args.dn_ask,
        spread=args.spread,
        top_ask_notional_usd=args.top_ask_notional,
        quote_age_sec=args.quote_age_sec,
    )
    decision = evaluate(profile, market)
    print(json.dumps(asdict(decision), indent=2))
    return 0 if decision.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
