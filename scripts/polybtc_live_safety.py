"""Pure safety helpers shared by the live runner.

No network / order placement. Unit-testable.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional

from polybtc_guardrails import GuardState, check_guards, new_state, register_result


def close_limit_price(
    entry_price: float,
    best_bid: Optional[float],
    *,
    aggressive_offset: float = 0.01,
    max_slippage_from_entry: float = 0.50,
    absolute_floor: float = 0.01,
    absolute_ceil: float = 0.99,
) -> float:
    """Compute a close limit price with a hard floor against dumping the book.

    Prefer best_bid - offset when available, but never below
    entry * (1 - max_slippage_from_entry).
    """
    entry = float(entry_price)
    floor = max(absolute_floor, entry * (1.0 - float(max_slippage_from_entry)))
    if best_bid is not None:
        candidate = float(best_bid) - float(aggressive_offset)
    else:
        candidate = floor
    px = max(floor, candidate)
    return max(absolute_floor, min(absolute_ceil, px))


def open_execution_env(profile: Dict[str, Any], base: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Env for child open-order process. Never disables spread/liquidity guards."""
    env = dict(base or {})
    spread = float(profile.get("skip_if_spread_gt", 0.03))
    min_notional = float(profile.get("skip_if_top_ask_notional_usd_lt", 30))
    # Only set defaults if the operator has not already configured them.
    env.setdefault("PM_MAX_SPREAD", str(spread))
    env.setdefault("PM_MIN_TOP_ASK_NOTIONAL_USD", str(min_notional))
    env.setdefault("PM_ORDER_TYPE", "FAK")
    return env


def stop_loss_price(entry_price: float, stop_loss_pct: float) -> float:
    return round(float(entry_price) * (1.0 - float(stop_loss_pct)), 8)


def build_guard_state_from_pnls(
    pnls: List[float],
    day: Optional[str] = None,
) -> GuardState:
    state = new_state(day)
    for pnl in pnls:
        state = register_result(state, float(pnl), day=day)
    return state


def guards_allow_entry(
    profile: Dict[str, Any],
    state: GuardState,
    account_equity: Optional[float] = None,
) -> Dict[str, Any]:
    return check_guards(profile, state, account_equity=account_equity)


def today_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def pnls_for_today_from_trades(trades: List[Dict[str, Any]], day: Optional[str] = None) -> List[float]:
    """Filter analytics trades (with unix ``ts``) to today's settled PnLs."""
    day = day or today_utc()
    out: List[float] = []
    for t in trades:
        pnl = t.get("pnl")
        if not isinstance(pnl, (int, float)):
            continue
        ts = t.get("ts")
        if ts is None:
            continue
        try:
            d = dt.datetime.fromtimestamp(float(ts), tz=dt.timezone.utc).date().isoformat()
        except (TypeError, ValueError, OSError):
            continue
        if d == day:
            out.append(float(pnl))
    return out
