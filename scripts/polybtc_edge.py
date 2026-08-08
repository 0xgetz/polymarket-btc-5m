#!/usr/bin/env python3
"""
PolyBTC Momentum — edge / break-even calculator.

Binary Up/Down payoff math for buying a side at price ``p`` (0..1):
  * stake $S buys S/p shares, each worth $1 on a win.
  * win  -> profit = S * (1 - p) / p
  * lose -> loss   = -S
  * break-even win-rate = p   (you must be right MORE than p% just to not lose)
  * positive edge        = win_prob - p  > 0

Pure math, no I/O or network — fully deterministic and testable.

CLI:
    python scripts/polybtc_edge.py --entry 0.71 --win-prob 0.80 --stake 5
    python scripts/polybtc_edge.py --table
"""
from __future__ import annotations

import argparse
import json


def win_payoff(entry_price: float, stake: float = 1.0) -> float:
    """Profit (in $) if the trade WINS, for a given stake."""
    if not 0 < entry_price < 1:
        raise ValueError("entry_price must be in (0, 1)")
    return stake * (1.0 - entry_price) / entry_price


def breakeven_winrate(entry_price: float) -> float:
    """Win-rate at which expected value is exactly zero (== entry price)."""
    if not 0 < entry_price < 1:
        raise ValueError("entry_price must be in (0, 1)")
    return entry_price


def ev_per_stake(entry_price: float, win_prob: float) -> float:
    """Expected value per $1 staked at the given entry price and win probability."""
    if not 0 < entry_price < 1:
        raise ValueError("entry_price must be in (0, 1)")
    if not 0 <= win_prob <= 1:
        raise ValueError("win_prob must be in [0, 1]")
    return win_prob * (1.0 - entry_price) / entry_price - (1.0 - win_prob)


def expected_value(entry_price: float, win_prob: float, stake: float = 1.0) -> float:
    """Expected value (in $) for a stake at the given entry price/win probability."""
    return stake * ev_per_stake(entry_price, win_prob)


def edge(entry_price: float, win_prob: float) -> float:
    """Edge = win_prob - break-even win-rate. Positive == favourable."""
    return win_prob - breakeven_winrate(entry_price)


def breakeven_table(prices=(0.60, 0.70, 0.71, 0.80, 0.90, 0.95), stake: float = 5.0):
    rows = []
    for p in prices:
        rows.append(
            {
                "entry": round(p, 4),
                "breakeven_winrate": round(breakeven_winrate(p), 4),
                "win_payoff_usd": round(win_payoff(p, stake), 4),
                "loss_usd": round(-stake, 4),
            }
        )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="PolyBTC Momentum edge / break-even calculator")
    ap.add_argument("--entry", type=float, help="entry price in (0,1)")
    ap.add_argument("--win-prob", type=float, default=None, help="your estimated win probability")
    ap.add_argument("--stake", type=float, default=5.0)
    ap.add_argument("--table", action="store_true", help="print break-even table and exit")
    args = ap.parse_args()

    if args.table or args.entry is None:
        print(json.dumps({"breakeven_table": breakeven_table(stake=args.stake)}, indent=2))
        if args.entry is None:
            return 0

    out = {
        "entry": args.entry,
        "stake_usd": args.stake,
        "breakeven_winrate": round(breakeven_winrate(args.entry), 4),
        "win_payoff_usd": round(win_payoff(args.entry, args.stake), 4),
        "loss_usd": round(-args.stake, 4),
    }
    if args.win_prob is not None:
        e = edge(args.entry, args.win_prob)
        out.update(
            {
                "win_prob": args.win_prob,
                "edge": round(e, 4),
                "ev_usd": round(expected_value(args.entry, args.win_prob, args.stake), 4),
                "verdict": "POSITIVE edge" if e > 0 else "NEGATIVE edge (do not trade)",
            }
        )
    print(json.dumps(out, indent=2))
    # exit 0 if positive edge (or no win-prob given), else 1
    if args.win_prob is not None and edge(args.entry, args.win_prob) <= 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
