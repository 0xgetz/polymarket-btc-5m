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
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class MarketSnapshot:
    seconds_left: float          # seconds remaining in the active 5m slot
    btc_move_usd: float          # signed BTC move in the active interval (close - open, $)
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
    skew_gap: Optional[float] = None           # chosen_ask - opposite_ask when available


@dataclass
class ConfirmTracker:
    """Require N consecutive GO decisions on the *same* side before entry.

    Filters one-tick spikes / flash skew that would otherwise pass a single poll.
    ``needed=1`` (default) means enter on the first GO — backward compatible.
    """

    needed: int = 1
    side: Optional[str] = None
    count: int = 0

    def update(self, decision: "Decision") -> Tuple[bool, int]:
        """Feed one preflight result. Returns ``(confirmed, streak)``."""
        need = max(1, int(self.needed))
        if not decision.ok or decision.side is None:
            self.side = None
            self.count = 0
            return False, 0
        if decision.side == self.side:
            self.count += 1
        else:
            self.side = decision.side
            self.count = 1
        return self.count >= need, self.count

    def reset(self) -> None:
        self.side = None
        self.count = 0


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

    # 2) Impulse confirmation: BTC move meets minimum (signed move, abs for size).
    move_min = profile["btc_move_usd_min"]
    abs_move = abs(market.btc_move_usd)
    ok_move = abs_move >= move_min
    checks["impulse_move"] = ok_move
    if not ok_move:
        reasons.append(f"btc_move ${abs_move:.0f} < min ${move_min:.0f}")

    # 2b) Optional max impulse: skip blow-off moves that reverse more often.
    move_max = profile.get("btc_move_usd_max")
    if move_max is not None:
        ok_max = abs_move <= float(move_max)
        checks["impulse_max"] = ok_max
        if not ok_max:
            reasons.append(f"btc_move ${abs_move:.0f} > max ${float(move_max):.0f}")

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

    # 6) Optional hard entry-window (target ± tolerance). Soft flag always set above.
    require_window = bool(profile.get("require_entry_window", False))
    if require_window:
        checks["entry_window"] = in_window
        if not in_window:
            reasons.append(
                f"seconds_left {market.seconds_left:.0f} outside entry window "
                f"{tgt - tol:.0f}–{tgt + tol:.0f}s"
            )

    # 7) Side selection (momentum): pick the side whose ask >= threshold; if
    #    both qualify, take the stronger (higher ask).
    thr = profile["threshold_price"]
    max_entry = profile.get("max_entry_price")
    candidates = []
    if market.up_ask is not None and market.up_ask >= thr:
        candidates.append(("UP", float(market.up_ask)))
    if market.dn_ask is not None and market.dn_ask >= thr:
        candidates.append(("DOWN", float(market.dn_ask)))
    # Drop absurdly rich prices (tiny payout; market already ~priced in).
    blocked_by_max_entry = False
    if max_entry is not None and candidates:
        capped = [(s, p) for s, p in candidates if p <= float(max_entry)]
        if not capped and candidates:
            blocked_by_max_entry = True
            reasons.append(
                f"all candidates above max_entry_price {float(max_entry):.2f} "
                f"({', '.join(f'{s}@{p:.2f}' for s, p in candidates)})"
            )
        candidates = capped
    side: Optional[str] = None
    entry_price: Optional[float] = None
    if candidates:
        side, entry_price = max(candidates, key=lambda c: c[1])
    ok_side = side is not None
    checks["threshold_side"] = ok_side
    if not ok_side and not blocked_by_max_entry:
        ua = "n/a" if market.up_ask is None else f"{market.up_ask:.2f}"
        da = "n/a" if market.dn_ask is None else f"{market.dn_ask:.2f}"
        reasons.append(f"no side >= threshold {thr:.2f} (UP {ua}, DOWN {da})")

    # 8) Direction alignment: BTC impulse *sign* must match chosen side.
    #    Prevents buying UP after a dump just because ask is still elevated.
    #    Requires a *signed* btc_move_usd (close - open), not abs().
    require_aligned = bool(profile.get("require_move_aligned", False))
    if require_aligned:
        aligned = False
        if side == "UP" and market.btc_move_usd > 0:
            aligned = True
        elif side == "DOWN" and market.btc_move_usd < 0:
            aligned = True
        checks["move_aligned"] = aligned if side is not None else False
        if side is not None and not aligned:
            reasons.append(
                f"btc_move ${market.btc_move_usd:+.0f} not aligned with side {side}"
            )
    elif side is not None:
        # Soft annotation only when filter is off.
        if (side == "UP" and market.btc_move_usd < 0) or (
            side == "DOWN" and market.btc_move_usd > 0
        ):
            reasons.append(
                f"note: btc_move ${market.btc_move_usd:+.0f} opposite to {side} "
                f"(enable require_move_aligned to block)"
            )

    # 9) Skew confirmation: chosen side must dominate the opposite ask by
    #    at least min_skew_gap (crowd + book already lean hard with momentum).
    skew_gap: Optional[float] = None
    min_skew = profile.get("min_skew_gap")
    if min_skew is not None and float(min_skew) > 0:
        min_skew_f = float(min_skew)
        if side == "UP" and market.up_ask is not None and market.dn_ask is not None:
            skew_gap = float(market.up_ask) - float(market.dn_ask)
            ok_skew = skew_gap >= min_skew_f
        elif side == "DOWN" and market.dn_ask is not None and market.up_ask is not None:
            skew_gap = float(market.dn_ask) - float(market.up_ask)
            ok_skew = skew_gap >= min_skew_f
        else:
            ok_skew = False
            skew_gap = None
        checks["skew_confirm"] = ok_skew if side is not None else False
        if side is not None and not ok_skew:
            gap_s = "n/a" if skew_gap is None else f"{skew_gap:.3f}"
            reasons.append(
                f"skew_gap {gap_s} < min_skew_gap {min_skew_f:.3f} for {side}"
            )
    elif side is not None and market.up_ask is not None and market.dn_ask is not None:
        if side == "UP":
            skew_gap = float(market.up_ask) - float(market.dn_ask)
        else:
            skew_gap = float(market.dn_ask) - float(market.up_ask)

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
        skew_gap=_round(skew_gap),
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
