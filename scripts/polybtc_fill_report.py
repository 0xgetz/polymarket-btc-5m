#!/usr/bin/env python3
"""
PolyBTC Momentum — fill / slippage report.

Compares signal entry (preflight ask) vs realized fill price from runtime logs.
Positive slippage_bps = paid more than signal (worse for buyer).

CLI:
    python scripts/polybtc_fill_report.py --runtime-dir ./runtime --limit 200
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def slippage_bps(signal_price: float, fill_price: float) -> float:
    """Buyer slippage in basis points: (fill - signal) / signal * 10000."""
    sig = float(signal_price)
    fill = float(fill_price)
    if sig <= 0:
        raise ValueError("signal_price must be > 0")
    return (fill - sig) / sig * 10000.0


def compute_fill_stats(fills: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate fill quality. Each fill needs signal_price, fill_price; optional side/pnl."""
    rows = []
    for f in fills:
        try:
            sig = float(f["signal_price"])
            fill = float(f["fill_price"])
            if not (0 < sig < 1 and 0 < fill < 1):
                continue
            bps = slippage_bps(sig, fill)
        except (KeyError, TypeError, ValueError):
            continue
        rows.append(
            {
                "side": f.get("side"),
                "signal_price": round(sig, 6),
                "fill_price": round(fill, 6),
                "slippage_bps": round(bps, 2),
                "pnl": f.get("pnl"),
                "file": f.get("file"),
            }
        )

    if not rows:
        return {"n_fills": 0, "note": "no fills with signal+fill prices"}

    bps_list = [r["slippage_bps"] for r in rows]
    worse = [b for b in bps_list if b > 0]
    better = [b for b in bps_list if b < 0]
    bps_sorted = sorted(bps_list)
    mid = len(bps_sorted) // 2

    by_side: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        side = r.get("side") or "unknown"
        b = by_side.setdefault(side, {"n": 0, "sum_bps": 0.0})
        b["n"] += 1
        b["sum_bps"] += r["slippage_bps"]
    for b in by_side.values():
        b["avg_slippage_bps"] = round(b["sum_bps"] / b["n"], 2) if b["n"] else None
        del b["sum_bps"]

    return {
        "n_fills": len(rows),
        "avg_slippage_bps": round(sum(bps_list) / len(bps_list), 2),
        "median_slippage_bps": bps_sorted[mid],
        "p90_slippage_bps": bps_sorted[int(0.9 * (len(bps_sorted) - 1))],
        "max_slippage_bps": max(bps_list),
        "min_slippage_bps": min(bps_list),
        "pct_worse_than_signal": round(len(worse) / len(rows), 4),
        "pct_better_than_signal": round(len(better) / len(rows), 4),
        "by_side": by_side,
        "worst_fills": sorted(rows, key=lambda r: r["slippage_bps"], reverse=True)[:5],
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


def load_fills_from_logs(runtime_dir: str, limit: int = 500) -> List[Dict[str, Any]]:
    """Extract signal vs fill prices from session logs."""
    files = sorted(
        set(glob.glob(os.path.join(runtime_dir, "polybtc_*.log"))),
        key=lambda p: os.path.getmtime(p),
    )[-limit:]
    fills: List[Dict[str, Any]] = []
    for f in files:
        obj = _load_tail_json(f)
        if not obj:
            continue
        opened = obj.get("opened") or {}
        pre = obj.get("preflight_on_entry") or obj.get("dry_run_decision") or {}
        signal = opened.get("signal_price")
        if signal is None:
            signal = pre.get("entry_price")
        fill = opened.get("entry_price")
        if signal is None or fill is None:
            continue
        fills.append(
            {
                "signal_price": signal,
                "fill_price": fill,
                "side": opened.get("side") or pre.get("side"),
                "pnl": obj.get("realized_cashflow_pnl_usdc"),
                "file": os.path.basename(f),
            }
        )
    return fills


def default_runtime_dir() -> str:
    return str(Path(__file__).resolve().parents[1] / "runtime")


def main() -> int:
    ap = argparse.ArgumentParser(description="PolyBTC fill / slippage report")
    ap.add_argument("--runtime-dir", default=default_runtime_dir())
    ap.add_argument("--limit", type=int, default=500)
    args = ap.parse_args()

    fills = load_fills_from_logs(args.runtime_dir, args.limit)
    out = {
        "runtime_dir": args.runtime_dir,
        "fill_stats": compute_fill_stats(fills),
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
