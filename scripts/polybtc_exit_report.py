#!/usr/bin/env python3
"""
PolyBTC Momentum — exit attribution report.

Breaks down settled trades by ``close_reason`` (stop_loss, early_cut_*,
hold_to_resolve_time_exit_*, time_exit_*, etc.) so you can see which exit
path helps or hurts expectancy.

Pure engine ``compute_exit_attribution`` is unit-testable without network.

CLI:
    python scripts/polybtc_exit_report.py --runtime-dir ./runtime --limit 200
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _normalise_reason(raw: Optional[str]) -> str:
    if not raw:
        return "unknown"
    r = str(raw).strip()
    if not r:
        return "unknown"
    # Collapse stop_loss_25pct → stop_loss family, early_cut_underwater_0.050 → early_cut_underwater
    if r.startswith("stop_loss"):
        return "stop_loss"
    if r.startswith("early_cut_underwater"):
        return "early_cut_underwater"
    if r.startswith("early_cut_btc_reverse"):
        return "early_cut_btc_reverse"
    if r.startswith("hold_to_resolve"):
        return "hold_to_resolve_time_exit"
    if r.startswith("time_exit"):
        return "time_exit"
    return r


def compute_exit_attribution(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate PnL by close_reason family.

    Each trade: ``pnl`` (required), optional ``close_reason``, ``side``.
    """
    settled = [t for t in trades if isinstance(t.get("pnl"), (int, float))]
    if not settled:
        return {
            "n_trades": 0,
            "by_reason": {},
            "note": "no settled trades with PnL found",
        }

    by: Dict[str, Dict[str, Any]] = {}
    for t in settled:
        reason = _normalise_reason(t.get("close_reason"))
        b = by.setdefault(
            reason,
            {
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "net_pnl": 0.0,
                "gross_profit": 0.0,
                "gross_loss": 0.0,
            },
        )
        pnl = float(t["pnl"])
        b["trades"] += 1
        b["net_pnl"] = round(b["net_pnl"] + pnl, 6)
        if pnl > 0:
            b["wins"] += 1
            b["gross_profit"] = round(b["gross_profit"] + pnl, 6)
        elif pnl < 0:
            b["losses"] += 1
            b["gross_loss"] = round(b["gross_loss"] + abs(pnl), 6)

    for reason, b in by.items():
        n = b["trades"]
        decided = b["wins"] + b["losses"]
        b["win_rate"] = round(b["wins"] / decided, 4) if decided else None
        b["expectancy"] = round(b["net_pnl"] / n, 6) if n else None
        gl = b["gross_loss"]
        gp = b["gross_profit"]
        b["profit_factor"] = (
            round(gp / gl, 4) if gl > 0 else (float("inf") if gp > 0 else 0.0)
        )

    # Rank reasons by net_pnl (worst first is useful for debugging)
    ranked = sorted(by.items(), key=lambda kv: kv[1]["net_pnl"])
    return {
        "n_trades": len(settled),
        "by_reason": by,
        "worst_reason": ranked[0][0] if ranked else None,
        "best_reason": ranked[-1][0] if ranked else None,
        "ranking_by_net_pnl_asc": [r for r, _ in ranked],
    }


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
    blob = txt[i + 1 :] if txt[i : i + 1] == "\n" else txt[i:]
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        return None


def load_exit_trades(runtime_dir: str, limit: int = 500) -> List[Dict[str, Any]]:
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
                "close_reason": closed.get("close_reason"),
                "result": obj.get("result"),
                "ts": os.path.getmtime(f),
                "file": os.path.basename(f),
            }
        )
    return trades


def default_runtime_dir() -> str:
    return str(Path(__file__).resolve().parents[1] / "runtime")


def main() -> int:
    ap = argparse.ArgumentParser(description="PolyBTC exit attribution report")
    ap.add_argument("--runtime-dir", default=default_runtime_dir())
    ap.add_argument("--limit", type=int, default=500)
    args = ap.parse_args()

    trades = load_exit_trades(args.runtime_dir, args.limit)
    out = {
        "runtime_dir": args.runtime_dir,
        "attribution": compute_exit_attribution(trades),
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
