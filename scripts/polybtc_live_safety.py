"""Pure safety helpers shared by the live runner.

No network / order placement. Unit-testable.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from polybtc_guardrails import GuardState, check_guards, new_state, register_result


@dataclass(frozen=True)
class ExitDecision:
    """Result of one position-monitor tick."""

    action: str  # "close" | "hold"
    reason: str
    effective_exit_before_sec: float
    hold_to_resolve: bool = False


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


def default_exit_policy() -> Dict[str, Any]:
    """Sane defaults when profile has no exit_policy block."""
    return {
        "enabled": True,
        "hold_to_resolve": {
            "enabled": True,
            "min_bid": 0.95,
            "max_seconds_left": 45,
            # When holding a near-certain side, exit much later (or ride to ~settle).
            "exit_before_sec": 3,
        },
        "early_cut": {
            "enabled": True,
            # Underwater near expiry → cut before the last-second dump / full SL path.
            "max_seconds_left": 40,
            "min_adverse_from_entry": 0.03,
            # Optional: cut if signed BTC move flips against the held side.
            "on_btc_reverse": True,
        },
    }


def merge_exit_policy(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Deep-merge profile exit_policy over defaults."""
    base = default_exit_policy()
    raw = profile.get("exit_policy")
    if not isinstance(raw, dict):
        return base
    out = dict(base)
    out["enabled"] = bool(raw.get("enabled", base["enabled"]))
    for key in ("hold_to_resolve", "early_cut"):
        block = dict(base.get(key) or {})
        override = raw.get(key) or {}
        if isinstance(override, dict):
            block.update(override)
        out[key] = block
    return out


def decide_exit(
    *,
    entry_price: float,
    best_bid: Optional[float],
    seconds_left: float,
    stop_loss_px: float,
    exit_before_sec: float,
    side: str = "UP",
    btc_move_usd: Optional[float] = None,
    exit_policy: Optional[Dict[str, Any]] = None,
) -> ExitDecision:
    """Decide whether to close a live position on this monitor tick.

    Priority (highest first):
      1. Hard stop-loss on executable bid
      2. Hold-to-resolve when bid is extreme and close is near (ride longer)
      3. Early-cut if underwater / BTC reverse near expiry
      4. Time exit at exit_before_sec (or hold policy's shorter exit_before)
      5. Otherwise keep holding
    """
    policy = exit_policy if exit_policy is not None else default_exit_policy()
    entry = float(entry_price)
    sec = float(seconds_left)
    base_exit = float(exit_before_sec)
    effective_exit = base_exit

    if not policy.get("enabled", True):
        if best_bid is not None and float(best_bid) <= float(stop_loss_px):
            return ExitDecision("close", "stop_loss", base_exit, False)
        if sec <= base_exit:
            return ExitDecision("close", f"time_exit_{int(base_exit)}s_before_end", base_exit)
        return ExitDecision("hold", "monitoring", base_exit)

    # 1) Hard stop-loss (always wins).
    if best_bid is not None and float(best_bid) <= float(stop_loss_px):
        return ExitDecision(
            "close",
            "stop_loss",
            effective_exit,
            hold_to_resolve=False,
        )

    hold_cfg = policy.get("hold_to_resolve") or {}
    holding = False
    if hold_cfg.get("enabled", True) and best_bid is not None:
        min_bid = float(hold_cfg.get("min_bid", 0.95))
        max_left = float(hold_cfg.get("max_seconds_left", 45))
        if float(best_bid) >= min_bid and sec <= max_left:
            holding = True
            effective_exit = min(
                base_exit,
                float(hold_cfg.get("exit_before_sec", 3)),
            )

    # 2) Early cut — only when NOT in hold-to-resolve mode.
    early = policy.get("early_cut") or {}
    if early.get("enabled", True) and not holding and best_bid is not None:
        max_left = float(early.get("max_seconds_left", 40))
        min_adv = float(early.get("min_adverse_from_entry", 0.03))
        if sec <= max_left and entry > 0:
            adverse = (entry - float(best_bid)) / entry
            if adverse >= min_adv:
                return ExitDecision(
                    "close",
                    f"early_cut_underwater_{adverse:.3f}",
                    effective_exit,
                )

        if early.get("on_btc_reverse", True) and btc_move_usd is not None and sec <= max_left:
            mv = float(btc_move_usd)
            side_u = str(side or "UP").upper()
            reversed_move = (side_u == "UP" and mv < 0) or (side_u == "DOWN" and mv > 0)
            if reversed_move:
                return ExitDecision(
                    "close",
                    f"early_cut_btc_reverse_{mv:+.0f}",
                    effective_exit,
                )

    # 3) Time exit (later if hold-to-resolve is active).
    if sec <= effective_exit:
        reason = (
            f"hold_to_resolve_time_exit_{int(effective_exit)}s"
            if holding
            else f"time_exit_{int(effective_exit)}s_before_end"
        )
        return ExitDecision("close", reason, effective_exit, hold_to_resolve=holding)

    if holding:
        return ExitDecision(
            "hold",
            "hold_to_resolve",
            effective_exit,
            hold_to_resolve=True,
        )
    return ExitDecision("hold", "monitoring", effective_exit, hold_to_resolve=False)


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
