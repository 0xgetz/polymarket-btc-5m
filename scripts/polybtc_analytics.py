#!/usr/bin/env python3
"""
PolyBTC Momentum — trade analytics / log backtest.

Turns the runtime trade logs (the JSON blob each run appends, see
``polybtc_report.py``) into honest performance statistics: real win-rate,
expectancy, profit factor, max drawdown, and loss/win streaks. Measuring the
actual hit-rate is the only responsible way to know whether the strategy has a
positive edge before sizing up — there is no guaranteed-profit shortcut.

The statistics engine ``compute_stats`` is pure (operates on a list of trade
dicts), so it is fully unit-testable without any log files.

CLI:
    python scripts/polybtc_analytics.py --runtime-dir ./runtime --limit 200
    python scripts/polybtc_analytics.py --breakeven
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def compute_stats(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute performance stats from an ordered (oldest->newest) list of trades.

    Each trade must have a numeric ``pnl``; optional keys: ``side``, ``ts``.
    """
    settled = [t for t in trades if isinstance(t.get("pnl"), (int, float))]
    n = len(settled)
    if n == 0:
        return {"n_trades": 0, "note": "no settled trades with PnL found"}

    wins = [t for t in settled if t["pnl"] > 0]
    losses = [t for t in settled if t["pnl"] < 0]
    breakeven = [t for t in settled if t["pnl"] == 0]
    decided = len(wins) + len(losses)

    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    net_pnl = sum(t["pnl"] for t in settled)

    # equity curve + max drawdown
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in settled:
        equity += t["pnl"]
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    # streaks
    cur_l = cur_w = max_l = max_w = 0
    for t in settled:
        if t["pnl"] < 0:
            cur_l += 1
            cur_w = 0
        elif t["pnl"] > 0:
            cur_w += 1
            cur_l = 0
        max_l = max(max_l, cur_l)
        max_w = max(max_w, cur_w)

    # per-side breakdown
    by_side: Dict[str, Dict[str, Any]] = {}
    for t in settled:
        side = t.get("side") or "unknown"
        b = by_side.setdefault(side, {"trades": 0, "wins": 0, "net_pnl": 0.0})
        b["trades"] += 1
        b["net_pnl"] = round(b["net_pnl"] + t["pnl"], 6)
        if t["pnl"] > 0:
            b["wins"] += 1
    for b in by_side.values():
        b["win_rate"] = round(b["wins"] / b["trades"], 4) if b["trades"] else None

    profit_factor = (
        round(gross_profit / gross_loss, 4) if gross_loss > 0
        else (float("inf") if gross_profit > 0 else 0.0)
    )

    return {
        "n_trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(breakeven),
        "win_rate": round(len(wins) / decided, 4) if decided else None,
        "net_pnl": round(net_pnl, 6),
        "gross_profit": round(gross_profit, 6),
        "gross_loss": round(gross_loss, 6),
        "profit_factor": profit_factor,
        "avg_win": round(gross_profit / len(wins), 6) if wins else None,
        "avg_loss": round(-gross_loss / len(losses), 6) if losses else None,
        "expectancy_per_trade": round(net_pnl / n, 6),
        "max_drawdown": round(max_dd, 6),
        "max_consecutive_losses": max_l,
        "max_consecutive_wins": max_w,
        "by_side": by_side,
    }


# --------------------------------------------------------------------------- #
# log parsing (mirrors polybtc_report.py's tail-JSON convention)
# --------------------------------------------------------------------------- #
def _load_tail_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        txt = open(path, "r", encoding="utf-8", errors="ignore").read()
    except OSError:
        return None
    i = txt.rfind("\n{")
    if i == -1 and txt.startswith("{"):
        i = 0
    if i == -1:
        return None
    blob = txt[i + 1:] if txt[i:i + 1] == "\n" else txt[i:]
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        return None


def load_runs_from_logs(runtime_dir: str, limit: int = 500) -> List[Dict[str, Any]]:
    """Parse runtime logs into ordered (oldest->newest) trade dicts."""
    files = sorted(
        set(glob.glob(os.path.join(runtime_dir, "polybtc_*.log"))),
        key=lambda p: os.path.getmtime(p),
    )[-limit:]
    trades: List[Dict[str, Any]] = []
    for f in files:
        obj = _load_tail_json(f)
        if not obj:
            continue
        pnl = obj.get("realized_cashflow_pnl_usdc")
        if not isinstance(pnl, (int, float)):
            continue
        closed = obj.get("closed") or {}
        opened = obj.get("opened") or {}
        trades.append(
            {
                "pnl": float(pnl),
                "side": opened.get("side"),
                "result": obj.get("result"),
                "close_reason": closed.get("close_reason"),
                "ts": os.path.getmtime(f),
                "file": os.path.basename(f),
            }
        )
    return trades


def default_runtime_dir() -> str:
    return str(Path(__file__).resolve().parents[1] / "runtime")


def main() -> int:
    ap = argparse.ArgumentParser(description="PolyBTC Momentum trade analytics")
    ap.add_argument("--runtime-dir", default=default_runtime_dir())
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--breakeven", action="store_true", help="also print break-even table")
    args = ap.parse_args()

    trades = load_runs_from_logs(args.runtime_dir, args.limit)
    out: Dict[str, Any] = {"runtime_dir": args.runtime_dir, "stats": compute_stats(trades)}

    if args.breakeven:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from polybtc_edge import breakeven_table  # noqa: E402
        out["breakeven_table"] = breakeven_table()

    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
