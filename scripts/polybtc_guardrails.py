#!/usr/bin/env python3
"""
PolyBTC Momentum — capital-protection guardrails.

Stateful risk controls that decide whether trading is still permitted:
  * consecutive-loss kill switch  (stop after N losses in a row)
  * daily max-loss cap            (stop when day's realized loss hits the cap)
  * max-trades-per-day ceiling    (avoid overtrading)
  * EV gate                       (only enter when estimated edge is positive)

All functions are pure/deterministic given the state, so they are fully
unit-testable. None of this guarantees profit — it limits how much a bad run
can cost and blocks negative-expectation entries.

CLI (replay a sequence of trade PnLs against a profile):
    python scripts/polybtc_guardrails.py --profile conservative \\
        --equity 200 --pnls=-5,-5,-5 --entry 0.71 --win-prob 0.80
    # note: use --pnls=... (equals form) so leading-minus values aren't parsed as flags
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


def _today() -> str:
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


@dataclass
class GuardState:
    day: str
    trades_today: int = 0
    realized_pnl_today: float = 0.0
    consecutive_losses: int = 0


def new_state(day: Optional[str] = None) -> GuardState:
    return GuardState(day=day or _today())


def register_result(state: GuardState, pnl: float, day: Optional[str] = None) -> GuardState:
    """Fold a settled trade's PnL into the guard state (resets counters on a new day)."""
    day = day or _today()
    if day != state.day:
        state = GuardState(day=day)
    state.trades_today += 1
    state.realized_pnl_today += float(pnl)
    if pnl < 0:
        state.consecutive_losses += 1
    elif pnl > 0:
        state.consecutive_losses = 0
    # pnl == 0 leaves the loss streak unchanged
    return state


def daily_loss_cap_usd(profile: Dict[str, Any], account_equity: float) -> float:
    """Daily max loss in $ derived from the profile's percentage and account equity."""
    return abs(account_equity) * float(profile["daily_max_loss_pct"]) / 100.0


def check_guards(
    profile: Dict[str, Any],
    state: GuardState,
    account_equity: Optional[float] = None,
    loss_cap_usd: Optional[float] = None,
) -> Dict[str, Any]:
    """Return {'allowed': bool, 'checks': {...}, 'reasons': [...]} for the next entry."""
    checks: Dict[str, bool] = {}
    reasons: List[str] = []

    max_streak = int(profile["max_consecutive_losses"])
    ok_streak = state.consecutive_losses < max_streak
    checks["consecutive_losses"] = ok_streak
    if not ok_streak:
        reasons.append(
            f"kill-switch: {state.consecutive_losses} consecutive losses >= {max_streak}"
        )

    max_trades = int(profile["max_trades_per_day"])
    ok_trades = state.trades_today < max_trades
    checks["max_trades_per_day"] = ok_trades
    if not ok_trades:
        reasons.append(f"daily trade ceiling reached: {state.trades_today}/{max_trades}")

    cap = loss_cap_usd
    if cap is None and account_equity is not None:
        cap = daily_loss_cap_usd(profile, account_equity)
    if cap is not None:
        ok_loss = state.realized_pnl_today > -abs(cap)
        checks["daily_loss_cap"] = ok_loss
        if not ok_loss:
            reasons.append(
                f"daily loss cap hit: {state.realized_pnl_today:.2f} <= -{abs(cap):.2f}"
            )

    allowed = all(checks.values())
    if allowed:
        reasons.insert(0, "OK: guardrails clear")
    return {"allowed": allowed, "checks": checks, "reasons": reasons,
            "state": asdict(state)}


def ev_gate(profile: Dict[str, Any], entry_price: float, est_win_prob: float) -> Dict[str, Any]:
    """Block entries without a positive edge buffer (est_win_prob >= price + min_edge)."""
    min_edge = float(profile.get("min_edge", 0.0))
    required = entry_price + min_edge
    edge = est_win_prob - entry_price
    allowed = est_win_prob >= required
    return {
        "allowed": allowed,
        "entry_price": round(entry_price, 4),
        "est_win_prob": round(est_win_prob, 4),
        "required_win_prob": round(required, 4),
        "edge": round(edge, 4),
        "min_edge": min_edge,
        "reason": (
            "positive edge >= buffer"
            if allowed
            else f"insufficient edge: need win_prob >= {required:.3f}"
        ),
    }


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from polybtc_config import load_config, validate_config, get_profile  # noqa: E402

    ap = argparse.ArgumentParser(description="PolyBTC Momentum guardrails")
    ap.add_argument("--config", default=None)
    ap.add_argument("--profile", default="conservative")
    ap.add_argument("--equity", type=float, default=None, help="account equity for daily loss cap")
    ap.add_argument("--pnls", default="", help="comma-separated settled PnLs to replay, e.g. -5,2,-5")
    ap.add_argument("--entry", type=float, default=None, help="entry price for EV gate check")
    ap.add_argument("--win-prob", type=float, default=None, help="estimated win prob for EV gate")
    args = ap.parse_args()

    cfg = load_config(args.config)
    errs = validate_config(cfg)
    if errs:
        print("ERROR: invalid config:", *(f"\n  - {e}" for e in errs), file=sys.stderr)
        return 2
    profile = get_profile(cfg, args.profile)

    state = new_state()
    if args.pnls.strip():
        for tok in args.pnls.split(","):
            tok = tok.strip()
            if tok:
                state = register_result(state, float(tok))

    out: Dict[str, Any] = {"guards": check_guards(profile, state, account_equity=args.equity)}
    if args.entry is not None and args.win_prob is not None:
        out["ev_gate"] = ev_gate(profile, args.entry, args.win_prob)

    print(json.dumps(out, indent=2))
    allowed = out["guards"]["allowed"] and out.get("ev_gate", {"allowed": True})["allowed"]
    return 0 if allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
