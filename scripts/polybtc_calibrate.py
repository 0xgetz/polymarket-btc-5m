#!/usr/bin/env python3
"""
PolyBTC Momentum — accuracy parameter calibrator.

Grid-search preflight filters against a historical CSV and rank combos by
expectancy / net PnL / profit factor. Uses the same ``run_backtest`` path as
live preflight so results stay comparable.

This is a measurement helper, not a promise of future profit. Prefer combos
that improve expectancy *and* still trade enough times to be meaningful.

CLI:
    python scripts/polybtc_calibrate.py \\
        --csv examples/polybtc_backtest_sample_data.csv \\
        --profile conservative --top 10
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from polybtc_backtest import load_csv, run_backtest


# Default grids (override via CLI). Kept modest so local runs stay fast.
DEFAULT_THRESHOLDS = (0.70, 0.75, 0.80, 0.82)
DEFAULT_SKEW_GAPS = (0.0, 0.12, 0.18, 0.25, 0.30)
DEFAULT_MOVE_MINS = (70.0, 85.0, 95.0)
DEFAULT_MOVE_MAXS = (None, 160.0, 200.0, 250.0)
DEFAULT_CONFIRM = (1,)  # multi-poll needs sequential same-market polls; CSV is usually 1 row/market


def _parse_floats(raw: str) -> List[Optional[float]]:
    """Parse comma list; empty token or 'none' → None (no cap / no filter)."""
    out: List[Optional[float]] = []
    for part in raw.split(","):
        p = part.strip().lower()
        if p in ("", "none", "null"):
            out.append(None)
        else:
            out.append(float(p))
    return out


def _parse_ints(raw: str) -> List[int]:
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def apply_overrides(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Return a shallow-copied profile with calibration knobs applied."""
    prof = deepcopy(base)
    for key, value in overrides.items():
        if value is None and key in ("btc_move_usd_max", "min_skew_gap"):
            prof[key] = None
        else:
            prof[key] = value
    return prof


def score_result(
    trades: int,
    expectancy_usd: float,
    net_pnl_usd: float,
    profit_factor: Optional[float],
    win_rate: float,
    min_trades: int,
) -> float:
    """Composite rank: primary expectancy, then PnL, with a trades floor penalty."""
    if trades < min_trades:
        # Still rankable but heavily penalized so they sink below viable combos.
        return -1000.0 + expectancy_usd + 0.01 * net_pnl_usd
    pf = profit_factor if profit_factor is not None else 0.0
    return (
        10.0 * expectancy_usd
        + 0.05 * net_pnl_usd
        + 0.5 * pf
        + 0.1 * win_rate
        + 0.01 * trades
    )


def iter_grid(
    thresholds: Sequence[float],
    skew_gaps: Sequence[Optional[float]],
    move_mins: Sequence[float],
    move_maxs: Sequence[Optional[float]],
    confirm_polls: Sequence[int],
    require_aligned: Sequence[bool],
) -> Iterable[Dict[str, Any]]:
    for thr, skew, mmin, mmax, conf, aligned in itertools.product(
        thresholds, skew_gaps, move_mins, move_maxs, confirm_polls, require_aligned
    ):
        if mmax is not None and mmax < mmin:
            continue
        yield {
            "threshold_price": float(thr),
            "min_skew_gap": None if skew is None or skew <= 0 else float(skew),
            "btc_move_usd_min": float(mmin),
            "btc_move_usd_max": float(mmax) if mmax is not None else None,
            "confirm_polls": int(conf),
            "require_move_aligned": bool(aligned),
        }


def calibrate(
    base_profile: Dict[str, Any],
    rows: List[Dict[str, str]],
    *,
    thresholds: Sequence[float] = DEFAULT_THRESHOLDS,
    skew_gaps: Sequence[Optional[float]] = DEFAULT_SKEW_GAPS,
    move_mins: Sequence[float] = DEFAULT_MOVE_MINS,
    move_maxs: Sequence[Optional[float]] = DEFAULT_MOVE_MAXS,
    confirm_polls: Sequence[int] = DEFAULT_CONFIRM,
    require_aligned: Sequence[bool] = (True,),
    min_trades: int = 1,
    top: int = 15,
    ev_gate: bool = False,
    min_edge: float = 0.0,
) -> Dict[str, Any]:
    """Run the grid and return ranked candidates + best combo."""
    candidates: List[Dict[str, Any]] = []
    grid = list(
        iter_grid(thresholds, skew_gaps, move_mins, move_maxs, confirm_polls, require_aligned)
    )

    for overrides in grid:
        profile = apply_overrides(base_profile, overrides)
        result = run_backtest(profile, rows, ev_gate=ev_gate, min_edge=min_edge)
        sc = score_result(
            result.trades,
            result.expectancy_usd,
            result.net_pnl_usd,
            result.profit_factor,
            result.win_rate,
            min_trades,
        )
        candidates.append(
            {
                "score": round(sc, 4),
                "params": overrides,
                "trades": result.trades,
                "signals": result.signals,
                "wins": result.wins,
                "losses": result.losses,
                "win_rate": result.win_rate,
                "net_pnl_usd": result.net_pnl_usd,
                "expectancy_usd": result.expectancy_usd,
                "profit_factor": result.profit_factor,
                "max_drawdown_usd": result.max_drawdown_usd,
                "avg_entry_price": result.avg_entry_price,
            }
        )

    candidates.sort(
        key=lambda c: (
            c["score"],
            c["expectancy_usd"],
            c["net_pnl_usd"],
            c["trades"],
        ),
        reverse=True,
    )
    top_n = candidates[: max(1, top)]
    return {
        "grid_size": len(grid),
        "rows": len(rows),
        "min_trades": min_trades,
        "best": top_n[0] if top_n else None,
        "top": top_n,
    }


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from polybtc_config import get_profile, load_config, validate_config  # noqa: PLC0415

    ap = argparse.ArgumentParser(
        description="Calibrate PolyBTC accuracy filters via CSV backtest grid search"
    )
    ap.add_argument("--csv", required=True, help="historical snapshot CSV path")
    ap.add_argument("--config", default=None)
    ap.add_argument("--profile", default="conservative", help="base profile to override")
    ap.add_argument(
        "--thresholds",
        default=",".join(str(x) for x in DEFAULT_THRESHOLDS),
        help="comma list of threshold_price values",
    )
    ap.add_argument(
        "--skew-gaps",
        default=",".join(str(x) for x in DEFAULT_SKEW_GAPS),
        help="comma list; use 0 or none to disable skew filter",
    )
    ap.add_argument(
        "--move-mins",
        default=",".join(str(x) for x in DEFAULT_MOVE_MINS),
        help="comma list of btc_move_usd_min",
    )
    ap.add_argument(
        "--move-maxs",
        default=",".join("none" if x is None else str(x) for x in DEFAULT_MOVE_MAXS),
        help="comma list of btc_move_usd_max (none = no cap)",
    )
    ap.add_argument(
        "--confirm-polls",
        default=",".join(str(x) for x in DEFAULT_CONFIRM),
        help="comma list (CSV usually has 1 row/market; keep 1 unless multi-poll data)",
    )
    ap.add_argument(
        "--require-aligned",
        default="true",
        choices=["true", "false", "both"],
        help="whether to require move alignment in the grid",
    )
    ap.add_argument("--min-trades", type=int, default=1, help="soft floor for ranking")
    ap.add_argument("--top", type=int, default=15, help="how many ranked combos to print")
    ap.add_argument("--ev-gate", action="store_true")
    ap.add_argument("--min-edge", type=float, default=0.0)
    args = ap.parse_args()

    cfg = load_config(args.config)
    errors = validate_config(cfg)
    if errors:
        print("ERROR: invalid config:", *(f"\n - {e}" for e in errors), file=sys.stderr)
        return 2

    base = get_profile(cfg, args.profile)
    if args.require_aligned == "true":
        aligned: Tuple[bool, ...] = (True,)
    elif args.require_aligned == "false":
        aligned = (False,)
    else:
        aligned = (True, False)

    report = calibrate(
        base,
        load_csv(args.csv),
        thresholds=[float(x) for x in args.thresholds.split(",") if x.strip()],
        skew_gaps=_parse_floats(args.skew_gaps),
        move_mins=[float(x) for x in args.move_mins.split(",") if x.strip()],
        move_maxs=_parse_floats(args.move_maxs),
        confirm_polls=_parse_ints(args.confirm_polls),
        require_aligned=aligned,
        min_trades=args.min_trades,
        top=args.top,
        ev_gate=args.ev_gate,
        min_edge=args.min_edge,
    )
    print(json.dumps(report, indent=2))
    best = report.get("best") or {}
    # Exit 0 if best expectancy is non-negative (or no trades found).
    if best and best.get("trades", 0) > 0 and best.get("expectancy_usd", 0) < 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
