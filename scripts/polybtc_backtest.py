#!/usr/bin/env python3
"""
PolyBTC Momentum - CSV historical backtester.

Replay recorded BTC 5m market snapshots through the same pure preflight gate used
by live/dry-run tooling. This is the first layer needed to prove whether a rule
set has positive expectancy before risking real capital.

Expected CSV columns:
    market_id,timestamp,seconds_left,btc_move_usd,up_ask,dn_ask,spread,
    top_ask_notional_usd,quote_age_sec,outcome

Optional columns:
    estimated_win_prob

Outcome must be UP/DOWN or win/loss. UP/DOWN is preferred because it lets the
engine compare the selected side against the resolved side.

CLI:
    python scripts/polybtc_backtest.py --csv examples/polybtc_backtest_sample.csv
    python scripts/polybtc_backtest.py --csv data.csv --ev-gate --min-edge 0.05
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from polybtc_edge import edge, expected_value
from polybtc_preflight import MarketSnapshot, evaluate


@dataclass
class BacktestTrade:
    market_id: str
    timestamp: str
    side: str
    outcome: str
    entry_price: float
    stake_usd: float
    pnl_usd: float
    win: bool
    estimated_win_prob: Optional[float]
    edge: Optional[float]
    ev_usd: Optional[float]
    reasons: List[str]


@dataclass
class BacktestResult:
    rows: int
    signals: int
    trades: int
    wins: int
    losses: int
    skipped_ev: int
    win_rate: float
    net_pnl_usd: float
    expectancy_usd: float
    profit_factor: Optional[float]
    max_drawdown_usd: float
    avg_entry_price: Optional[float]
    avg_edge: Optional[float]
    by_side: Dict[str, Dict[str, float]]
    trades_detail: List[BacktestTrade]


def _parse_float(row: Dict[str, str], key: str, default: Optional[float] = None) -> Optional[float]:
    value = row.get(key, "")
    if value is None or str(value).strip() == "":
        return default
    return float(value)


def _parse_snapshot(row: Dict[str, str]) -> MarketSnapshot:
    return MarketSnapshot(
        seconds_left=float(row["seconds_left"]),
        btc_move_usd=float(row["btc_move_usd"]),
        up_ask=_parse_float(row, "up_ask"),
        dn_ask=_parse_float(row, "dn_ask"),
        spread=float(row.get("spread", 0) or 0),
        top_ask_notional_usd=float(row.get("top_ask_notional_usd", 0) or 0),
        quote_age_sec=float(row.get("quote_age_sec", 0) or 0),
    )


def _normalise_outcome(raw: str, selected_side: str) -> Tuple[str, bool]:
    outcome = raw.strip().upper()
    if outcome in {"UP", "DOWN"}:
        return outcome, outcome == selected_side
    if outcome in {"WIN", "WON", "TRUE", "1"}:
        return selected_side, True
    if outcome in {"LOSS", "LOSE", "LOST", "FALSE", "0"}:
        return ("DOWN" if selected_side == "UP" else "UP"), False
    raise ValueError(f"unknown outcome '{raw}'; use UP/DOWN or win/loss")


def _trade_pnl(entry_price: float, stake: float, win: bool) -> float:
    if win:
        return stake * (1.0 - entry_price) / entry_price
    return -stake


def _max_drawdown(pnls: Iterable[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _side_summary(trades: List[BacktestTrade]) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for side in ("UP", "DOWN"):
        side_trades = [t for t in trades if t.side == side]
        wins = sum(1 for t in side_trades if t.win)
        count = len(side_trades)
        pnl = sum(t.pnl_usd for t in side_trades)
        out[side] = {
            "trades": float(count),
            "wins": float(wins),
            "win_rate": round(wins / count, 4) if count else 0.0,
            "net_pnl_usd": round(pnl, 4),
        }
    return out


def run_backtest(
    profile: Dict[str, Any],
    rows: Iterable[Dict[str, str]],
    *,
    ev_gate: bool = False,
    min_edge: float = 0.0,
) -> BacktestResult:
    """Replay CSV rows and return aggregate performance statistics."""
    row_count = 0
    signals = 0
    skipped_ev = 0
    trades: List[BacktestTrade] = []

    for row in rows:
        row_count += 1
        decision = evaluate(profile, _parse_snapshot(row))
        if not decision.ok:
            continue
        signals += 1

        if decision.side is None or decision.entry_price is None or decision.stake_usd is None:
            continue

        est_prob = _parse_float(row, "estimated_win_prob")
        trade_edge = edge(decision.entry_price, est_prob) if est_prob is not None else None
        trade_ev = (
            expected_value(decision.entry_price, est_prob, decision.stake_usd)
            if est_prob is not None
            else None
        )
        if ev_gate and (trade_edge is None or trade_edge < min_edge):
            skipped_ev += 1
            continue

        outcome, won = _normalise_outcome(row["outcome"], decision.side)
        pnl = _trade_pnl(decision.entry_price, decision.stake_usd, won)
        trades.append(
            BacktestTrade(
                market_id=row.get("market_id", str(row_count)),
                timestamp=row.get("timestamp", ""),
                side=decision.side,
                outcome=outcome,
                entry_price=decision.entry_price,
                stake_usd=decision.stake_usd,
                pnl_usd=round(pnl, 4),
                win=won,
                estimated_win_prob=est_prob,
                edge=round(trade_edge, 4) if trade_edge is not None else None,
                ev_usd=round(trade_ev, 4) if trade_ev is not None else None,
                reasons=decision.reasons,
            )
        )

    wins = sum(1 for t in trades if t.win)
    losses = len(trades) - wins
    gross_profit = sum(t.pnl_usd for t in trades if t.pnl_usd > 0)
    gross_loss = abs(sum(t.pnl_usd for t in trades if t.pnl_usd < 0))
    net_pnl = sum(t.pnl_usd for t in trades)
    entries = [t.entry_price for t in trades]
    edges = [t.edge for t in trades if t.edge is not None]

    return BacktestResult(
        rows=row_count,
        signals=signals,
        trades=len(trades),
        wins=wins,
        losses=losses,
        skipped_ev=skipped_ev,
        win_rate=round(wins / len(trades), 4) if trades else 0.0,
        net_pnl_usd=round(net_pnl, 4),
        expectancy_usd=round(net_pnl / len(trades), 4) if trades else 0.0,
        profit_factor=round(gross_profit / gross_loss, 4) if gross_loss else None,
        max_drawdown_usd=round(_max_drawdown(t.pnl_usd for t in trades), 4),
        avg_entry_price=round(sum(entries) / len(entries), 4) if entries else None,
        avg_edge=round(sum(edges) / len(edges), 4) if edges else None,
        by_side=_side_summary(trades),
        trades_detail=trades,
    )


def load_csv(path: str) -> List[Dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from polybtc_config import get_profile, load_config, validate_config  # noqa: PLC0415

    ap = argparse.ArgumentParser(description="PolyBTC Momentum CSV backtester")
    ap.add_argument("--csv", required=True, help="historical snapshot CSV path")
    ap.add_argument("--config", default=None, help="path to polybtc_profiles.yaml")
    ap.add_argument("--profile", default="conservative")
    ap.add_argument("--ev-gate", action="store_true", help="require estimated_win_prob edge")
    ap.add_argument("--min-edge", type=float, default=0.0, help="minimum win_prob - entry_price")
    ap.add_argument("--trades", action="store_true", help="include per-trade rows in JSON output")
    args = ap.parse_args()

    cfg = load_config(args.config)
    errors = validate_config(cfg)
    if errors:
        print("ERROR: invalid config:", *(f"\n - {e}" for e in errors), file=sys.stderr)
        return 2

    profile = get_profile(cfg, args.profile)
    result = run_backtest(profile, load_csv(args.csv), ev_gate=args.ev_gate, min_edge=args.min_edge)
    payload = asdict(result)
    if not args.trades:
        payload.pop("trades_detail", None)
    print(json.dumps(payload, indent=2))
    return 0 if result.net_pnl_usd >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
