#!/usr/bin/env python3
"""
PolyBTC Momentum — dry-run (paper trading) recorder.

Dry-run mode means: run the SAME preflight decision logic as live, but place no
real order. Instead, record a *paper trade* with the simulated PnL once the
market resolves. The records are written in the same JSON-blob log format the
live runner uses, so ``polybtc_analytics.py`` / ``polybtc_report.py`` /
``polybtc_daily_summary.py`` all work identically on paper or live data.

This lets you validate the strategy's REAL hit-rate for a few days before
risking any money — the only honest way to know whether the edge is positive
(remember: we are competing against many smart, fast participants).

The decision + simulation logic is pure and deterministic; only ``write_paper_log``
touches the filesystem.

CLI (record one resolved paper trade):
    python scripts/polybtc_dryrun.py --profile conservative \\
        --seconds-left 118 --btc-move-usd 84 --up-ask 0.71 --dn-ask 0.29 \\
        --spread 0.02 --top-ask-notional 41 --quote-age-sec 1 \\
        --market-slug btc-updown-5m-1430 --outcome UP
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Sibling imports work both when run as a script (scripts/ on sys.path[0])
# and under pytest (tests/conftest.py adds scripts/ to sys.path).
from polybtc_preflight import MarketSnapshot, evaluate
from polybtc_edge import win_payoff


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(ts: dt.datetime) -> str:
    return ts.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def simulate_trade(
    profile: Dict[str, Any],
    market: MarketSnapshot,
    outcome: str,
    market_slug: Optional[str] = None,
    ts: Optional[dt.datetime] = None,
) -> Dict[str, Any]:
    """Run the preflight gate and, if it's a GO, simulate the trade outcome.

    ``outcome`` is either 'win' / 'loss', or the resolved winning side
    'UP' / 'DOWN'. Returns a record dict in the analytics-compatible log schema.
    """
    ts = ts or _now_utc()
    decision = evaluate(profile, market)

    base = {
        "mode": "dry_run",
        "ts_utc": _iso(ts),
        "preflight": {
            "ok": decision.ok,
            "side": decision.side,
            "checks": decision.checks,
            "reasons": decision.reasons,
        },
    }

    if not decision.ok:
        base["result"] = "no_entry"
        base["opened"] = None
        base["closed"] = None
        return base

    o = str(outcome).strip()
    if o.lower() in ("win", "loss"):
        won = o.lower() == "win"
    elif o.upper() in ("UP", "DOWN"):
        won = o.upper() == decision.side
    else:
        raise ValueError("outcome must be one of: win, loss, UP, DOWN")

    entry = float(decision.entry_price)
    stake = float(decision.stake_usd)
    pnl = win_payoff(entry, stake) if won else -stake

    base["result"] = "win" if won else "loss"
    base["opened"] = {
        "side": decision.side,
        "entry_price": round(entry, 4),
        "stake_usd": round(stake, 4),
        "market_slug": market_slug,
    }
    base["closed"] = {
        "close_status": "settled_paper",
        "winning_side": decision.side if won else ("DOWN" if decision.side == "UP" else "UP"),
    }
    base["realized_cashflow_pnl_usdc"] = round(pnl, 6)
    base["stop_loss_price"] = decision.stop_loss_price
    base["hedge"] = decision.hedge
    return base


def paper_log_path(runtime_dir: str, ts: Optional[dt.datetime] = None) -> str:
    ts = ts or _now_utc()
    stamp = ts.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    return os.path.join(runtime_dir, f"polybtc_dryrun_{stamp}.log")


def write_paper_log(record: Dict[str, Any], runtime_dir: str, ts: Optional[dt.datetime] = None) -> str:
    """Write a paper-trade record to an analytics-compatible .log file."""
    os.makedirs(runtime_dir, exist_ok=True)
    path = paper_log_path(runtime_dir, ts)
    op = record.get("opened") or {}
    pnl = record.get("realized_cashflow_pnl_usdc")
    header = (
        f"[dry-run] {record.get('ts_utc')} result={record.get('result')} "
        f"slug={op.get('market_slug')} side={op.get('side')} "
        f"entry={op.get('entry_price')} stake={op.get('stake_usd')} "
        f"pnl={pnl}"
    )
    # The JSON blob MUST be the final block (preceded by a newline) so the
    # tail-JSON readers in analytics/report pick it up.
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(header + "\n" + json.dumps(record))
    return path


def default_runtime_dir() -> str:
    return str(Path(__file__).resolve().parents[1] / "runtime")


def main() -> int:
    # Use the validated config for the resolved profile.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from polybtc_config import load_config, validate_config, get_profile  # noqa: E402

    ap = argparse.ArgumentParser(description="PolyBTC Momentum dry-run (paper) recorder")
    ap.add_argument("--config", default=None)
    ap.add_argument("--profile", default="conservative")
    ap.add_argument("--runtime-dir", default=default_runtime_dir())
    ap.add_argument("--seconds-left", type=float, required=True)
    ap.add_argument("--btc-move-usd", type=float, required=True)
    ap.add_argument("--up-ask", type=float, default=None)
    ap.add_argument("--dn-ask", type=float, default=None)
    ap.add_argument("--spread", type=float, default=0.0)
    ap.add_argument("--top-ask-notional", type=float, default=0.0)
    ap.add_argument("--quote-age-sec", type=float, default=0.0)
    ap.add_argument("--market-slug", default=None)
    ap.add_argument("--outcome", required=True, help="win | loss | UP | DOWN (resolved result)")
    ap.add_argument("--no-write", action="store_true", help="print record but do not write a log")
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
    record = simulate_trade(profile, market, args.outcome, market_slug=args.market_slug)
    if not args.no_write and record["result"] != "no_entry":
        path = write_paper_log(record, args.runtime_dir)
        record["_log"] = path
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
