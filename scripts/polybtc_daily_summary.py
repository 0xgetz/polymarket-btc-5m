#!/usr/bin/env python3
"""
PolyBTC Momentum — daily summary.

Aggregates a single day's trade logs (paper or live) into an honest performance
digest: trades, win-rate, net PnL, profit factor, max drawdown, worst loss
streak, plus risk-context flags (kill-switch / daily-loss-cap proximity). Render
as Markdown/text or JSON, optionally write to a file, and optionally POST to a
webhook (Slack / Discord / Telegram-compatible) for an automated daily report.

Designed to be run from cron on the machine where trading happens — see
``scripts/polybtc_daily_cron.sh``.

The aggregation logic (``filter_by_date`` / ``build_summary`` / ``render_text``)
is pure and unit-tested.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from polybtc_analytics import compute_stats, load_runs_from_logs


def today_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def filter_by_date(trades: List[Dict[str, Any]], date_iso: str) -> List[Dict[str, Any]]:
    """Keep trades whose UTC date (from epoch 'ts') matches date_iso (YYYY-MM-DD)."""
    out = []
    for t in trades:
        ts = t.get("ts")
        if ts is None:
            continue
        d = dt.datetime.fromtimestamp(float(ts), dt.timezone.utc).date().isoformat()
        if d == date_iso:
            out.append(t)
    return out


def build_summary(
    trades: List[Dict[str, Any]],
    date_iso: str,
    profile: Optional[Dict[str, Any]] = None,
    equity: Optional[float] = None,
) -> Dict[str, Any]:
    """Compute the day's stats plus risk-context flags."""
    stats = compute_stats(trades)
    summary: Dict[str, Any] = {"date": date_iso, "stats": stats}

    risk: Dict[str, Any] = {}
    if profile:
        max_streak = int(profile.get("max_consecutive_losses", 0) or 0)
        worst_streak = int(stats.get("max_consecutive_losses", 0) or 0)
        risk["max_consecutive_losses_limit"] = max_streak
        risk["worst_loss_streak_today"] = worst_streak
        risk["kill_switch_would_trip"] = bool(max_streak and worst_streak >= max_streak)

        if equity is not None and "daily_max_loss_pct" in profile:
            cap = abs(equity) * float(profile["daily_max_loss_pct"]) / 100.0
            net = float(stats.get("net_pnl", 0.0) or 0.0)
            risk["daily_loss_cap_usd"] = round(cap, 2)
            risk["net_pnl_vs_cap"] = round(net, 2)
            risk["daily_loss_cap_hit"] = net <= -cap
    summary["risk"] = risk
    return summary


def render_text(summary: Dict[str, Any]) -> str:
    s = summary.get("stats", {})
    risk = summary.get("risk", {})
    lines = [f"📊 PolyBTC Momentum — Daily Summary ({summary['date']} UTC)", ""]

    if s.get("n_trades", 0) == 0:
        lines.append("No settled trades recorded for this day.")
        return "\n".join(lines)

    wr = s.get("win_rate")
    pf = s.get("profit_factor")
    lines += [
        f"• Trades: {s['n_trades']}  (W {s['wins']} / L {s['losses']}"
        + (f" / BE {s['breakeven']}" if s.get("breakeven") else "") + ")",
        f"• Win-rate: {wr*100:.1f}%" if wr is not None else "• Win-rate: n/a",
        f"• Net PnL: {s['net_pnl']:+.2f} USDC",
        f"• Expectancy/trade: {s['expectancy_per_trade']:+.3f} USDC",
        f"• Profit factor: {pf if pf != float('inf') else '∞'}",
        f"• Avg win / avg loss: "
        f"{(s.get('avg_win') or 0):+.2f} / {(s.get('avg_loss') or 0):+.2f}",
        f"• Max drawdown: {s['max_drawdown']:.2f} USDC",
        f"• Worst loss streak: {s['max_consecutive_losses']}",
    ]

    if risk:
        lines.append("")
        if risk.get("kill_switch_would_trip"):
            lines.append(
                f"⚠️ Loss streak {risk['worst_loss_streak_today']} >= limit "
                f"{risk['max_consecutive_losses_limit']} — kill-switch territory."
            )
        if risk.get("daily_loss_cap_hit"):
            lines.append(
                f"⚠️ Daily loss cap hit: {risk['net_pnl_vs_cap']:+.2f} "
                f"<= -{risk['daily_loss_cap_usd']:.2f} USDC."
            )
        if not risk.get("kill_switch_would_trip") and not risk.get("daily_loss_cap_hit"):
            lines.append("✅ Within risk limits.")

    lines += ["", "_Dry-run/live paper figures. No setup guarantees profit._"]
    return "\n".join(lines)


def _post_webhook(url: str, text: str) -> int:
    import urllib.request  # local import; stdlib only

    # Send both keys so it works with Slack ('text') and Discord ('content').
    payload = json.dumps({"text": text, "content": text}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
        return resp.status


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    ap = argparse.ArgumentParser(description="PolyBTC Momentum daily summary")
    ap.add_argument("--runtime-dir", default=str(Path(__file__).resolve().parents[1] / "runtime"))
    ap.add_argument("--date", default=today_utc(), help="YYYY-MM-DD (UTC); default today")
    ap.add_argument("--profile", default=None, help="resolve a profile for risk context")
    ap.add_argument("--config", default=None)
    ap.add_argument("--equity", type=float, default=None, help="account equity for loss-cap context")
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--out", default=None, help="write Markdown to this file (or dir)")
    ap.add_argument("--json", action="store_true", help="print JSON instead of text")
    ap.add_argument("--webhook", default=None, help="POST the summary to this URL")
    args = ap.parse_args()

    profile = None
    if args.profile:
        from polybtc_config import load_config, validate_config, get_profile  # noqa: E402
        cfg = load_config(args.config)
        errs = validate_config(cfg)
        if errs:
            print("ERROR: invalid config:", *(f"\n  - {e}" for e in errs), file=sys.stderr)
            return 2
        profile = get_profile(cfg, args.profile)

    all_trades = load_runs_from_logs(args.runtime_dir, args.limit)
    day_trades = filter_by_date(all_trades, args.date)
    summary = build_summary(day_trades, args.date, profile=profile, equity=args.equity)
    text = render_text(summary)

    if args.out:
        out = args.out
        if os.path.isdir(out):
            out = os.path.join(out, f"summary_{args.date}.md")
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        summary["_out"] = out

    if args.webhook:
        try:
            status = _post_webhook(args.webhook, text)
            summary["_webhook_status"] = status
        except Exception as exc:  # noqa: BLE001
            summary["_webhook_error"] = str(exc)

    print(json.dumps(summary, indent=2) if args.json else text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
