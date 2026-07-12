#!/usr/bin/env python3
"""PolyBTC Momentum — canonical live/session runner.

Risk gates (preflight + capital guardrails) run BEFORE any open order.
Profile source of truth: config/polybtc_profiles.yaml via polybtc_config.
Default is dry-run unless --execute is set.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

import requests

# Sibling modules (scripts/ on path when run as script or via PYTHONPATH)
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from polybtc_analytics import load_runs_from_logs  # noqa: E402
from polybtc_config import get_profile, load_config, validate_config  # noqa: E402
from polybtc_guardrails import check_guards  # noqa: E402
from polybtc_live_safety import (  # noqa: E402
    build_guard_state_from_pnls,
    close_limit_price,
    decide_exit,
    merge_exit_policy,
    open_execution_env,
    pnls_for_today_from_trades,
    stop_loss_price,
    today_utc,
)
from polybtc_preflight import ConfirmTracker, MarketSnapshot, evaluate  # noqa: E402

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.constants import POLYGON
    from py_clob_client.clob_types import ApiCreds
except ImportError:  # pragma: no cover - optional until live stack installed
    ClobClient = None  # type: ignore
    POLYGON = 137
    ApiCreds = None  # type: ignore

UTC = dt.timezone.utc


def now_utc() -> dt.datetime:
    return dt.datetime.now(UTC)


def ts_utc() -> str:
    return now_utc().isoformat().replace("+00:00", "Z")


def parse_json_objects(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cur: list[str] = []
    depth = 0
    for ch in text:
        if ch == "{":
            depth += 1
        if depth > 0:
            cur.append(ch)
        if ch == "}" and depth > 0:
            depth -= 1
            if depth == 0:
                s = "".join(cur)
                cur = []
                try:
                    out.append(json.loads(s))
                except Exception:
                    pass
    return out


def bucket_5m(ts: int) -> int:
    return ts - (ts % 300)


def fetch_event(slug: str) -> Optional[dict[str, Any]]:
    r = requests.get(
        "https://gamma-api.polymarket.com/events",
        params={"slug": slug},
        timeout=12,
    )
    r.raise_for_status()
    arr = r.json()
    return arr[0] if arr else None


def resolve_active_current_5m_market() -> Optional[dict[str, Any]]:
    """Return active BTC 5m market for the current slot only."""
    now = int(time.time())
    cur = bucket_5m(now)
    slug = f"btc-updown-5m-{cur}"

    try:
        ev = fetch_event(slug)
    except Exception:
        return None
    if not ev:
        return None

    mkts = ev.get("markets") or []
    if not mkts:
        return None

    m = mkts[0]
    if m.get("closed") is True:
        return None
    if m.get("active") is False:
        return None

    end_iso = str(m.get("endDate") or m.get("endDateIso") or "")
    try:
        end_ts = dt.datetime.fromisoformat(end_iso.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None

    sec_left = end_ts - time.time()
    if sec_left <= 5:
        return None

    mm = dict(m)
    mm["_event_slug"] = slug
    mm["_seconds_left"] = sec_left
    return mm


def parse_json_field(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return v
    return v


def market_side_prices(market: dict[str, Any]) -> tuple[float, float, str, str, str, str]:
    outcomes = parse_json_field(market.get("outcomes")) or []
    prices = parse_json_field(market.get("outcomePrices")) or []
    token_ids = parse_json_field(market.get("clobTokenIds")) or []
    if len(prices) < 2 or len(token_ids) < 2:
        raise RuntimeError("missing outcomePrices/clobTokenIds")

    up_i, down_i = 0, 1
    labs = [str(x).lower() for x in outcomes[:2]] if isinstance(outcomes, list) else []
    if len(labs) >= 2 and ("up" in labs[1] or "yes" in labs[1]):
        up_i, down_i = 1, 0

    up_p = float(prices[up_i])
    dn_p = float(prices[down_i])
    up_t = str(token_ids[up_i])
    dn_t = str(token_ids[down_i])
    return (
        up_p,
        dn_p,
        up_t,
        dn_t,
        str(market.get("slug") or market.get("_event_slug") or ""),
        str(market.get("endDate") or market.get("endDateIso") or ""),
    )


def _order_price_size(level) -> tuple[Optional[float], float]:
    if level is None:
        return None, 0.0
    if isinstance(level, dict):
        p = level.get("price")
        s = level.get("size") or level.get("amount") or 0
    else:
        p = getattr(level, "price", None)
        s = getattr(level, "size", None) or getattr(level, "amount", None) or 0
    try:
        return (float(p) if p is not None else None), float(s or 0)
    except (TypeError, ValueError):
        return None, 0.0


def _best_bid_ask(book) -> tuple[Optional[float], Optional[float], float, float]:
    """Return best_bid, best_ask, top_bid_notional, top_ask_notional."""
    bids = getattr(book, "bids", None) or (book.get("bids") if isinstance(book, dict) else []) or []
    asks = getattr(book, "asks", None) or (book.get("asks") if isinstance(book, dict) else []) or []
    best_bid = None
    best_ask = None
    bid_sz = 0.0
    ask_sz = 0.0
    for b in bids:
        p, s = _order_price_size(b)
        if p is None:
            continue
        if best_bid is None or p > best_bid:
            best_bid = p
            bid_sz = s
    for a in asks:
        p, s = _order_price_size(a)
        if p is None:
            continue
        if best_ask is None or p < best_ask:
            best_ask = p
            ask_sz = s
    bid_notional = (best_bid or 0.0) * bid_sz
    ask_notional = (best_ask or 0.0) * ask_sz
    return best_bid, best_ask, bid_notional, ask_notional


def _require_clob():
    if ClobClient is None:
        raise RuntimeError(
            "py_clob_client is not installed; install live deps "
            "(pip install -r requirements-live.txt) inside the trading venv"
        )


def clob_side_snapshot(
    up_token: str,
    down_token: str,
    clob_base: str = "https://clob.polymarket.com",
) -> dict[str, Any]:
    """CLOB snapshot for preflight: asks, spreads, top notional, quote age (0 when fresh)."""
    _require_clob()
    pub = ClobClient(host=clob_base, chain_id=POLYGON)
    up_book = pub.get_order_book(str(up_token))
    dn_book = pub.get_order_book(str(down_token))
    up_bid, up_ask, _, up_ask_n = _best_bid_ask(up_book)
    dn_bid, dn_ask, _, dn_ask_n = _best_bid_ask(dn_book)

    spreads: list[float] = []
    if up_ask is not None and up_bid is not None:
        spreads.append(max(0.0, up_ask - up_bid))
    if dn_ask is not None and dn_bid is not None:
        spreads.append(max(0.0, dn_ask - dn_bid))

    # Notional for the stronger side will be chosen later; expose both.
    return {
        "up_ask": up_ask,
        "dn_ask": dn_ask,
        "up_bid": up_bid,
        "dn_bid": dn_bid,
        "up_ask_notional": up_ask_n,
        "dn_ask_notional": dn_ask_n,
        "min_spread": min(spreads) if spreads else None,
        "quote_age_sec": 0.0,  # just fetched
    }


def clob_best_bid(token_id: str, clob_base: str = "https://clob.polymarket.com") -> Optional[float]:
    _require_clob()
    pub = ClobClient(host=clob_base, chain_id=POLYGON)
    book = pub.get_order_book(str(token_id))
    best_bid, _, _, _ = _best_bid_ask(book)
    return best_bid


def btc_move_usd_current_5m() -> Optional[float]:
    """Signed USD move of BTCUSDT in the current 5m Binance candle (close - open).

    Sign is required for ``require_move_aligned`` (UP needs positive move,
    DOWN needs negative). Preflight uses ``abs(move)`` for size filters.
    """
    try:
        now = int(time.time())
        start_ms = (now - (now % 300)) * 1000
        r = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={
                "symbol": "BTCUSDT",
                "interval": "5m",
                "startTime": start_ms,
                "limit": 1,
            },
            timeout=10,
        )
        r.raise_for_status()
        arr = r.json()
        if not arr:
            return None
        o = float(arr[0][1])
        c = float(arr[0][4])
        return c - o
    except Exception:
        return None


def auth_clob_client(clob_base: str = "https://clob.polymarket.com"):
    try:
        _require_clob()
        key = os.getenv("PM_PRIVATE_KEY") or ""
        funder = os.getenv("PM_FUNDER") or os.getenv("PM_ADDRESS") or None
        sig = int(os.getenv("PM_SIGNATURE_TYPE", "2"))
        v1 = os.getenv("PM_API_KEY") or ""
        v2 = os.getenv("PM_API_SECRET") or ""
        v3 = os.getenv("PM_API_PASSPHRASE") or ""
        if not key or not v1 or not v2 or not v3:
            return None
        c = ClobClient(
            host=clob_base,
            chain_id=POLYGON,
            key=key,
            signature_type=sig,
            funder=funder,
        )
        creds = {
            f"api_{'key'}": v1,
            f"api_{'secret'}": v2,
            f"api_{'passphrase'}": v3,
        }
        c.set_api_creds(ApiCreds(**creds))
        return c
    except Exception:
        return None


def poll_order_status(
    client,
    order_id: str,
    wait_sec: float = 6.0,
    step_sec: float = 1.0,
) -> tuple[str, Optional[dict[str, Any]]]:
    if client is None or not order_id:
        return "", None
    deadline = time.time() + max(0.0, float(wait_sec))
    last = None
    while time.time() <= deadline:
        try:
            last = client.get_order(order_id)
            st = str((last or {}).get("status") or "").upper()
            if st and st not in ("LIVE", "OPEN"):
                return st, last
        except Exception:
            pass
        time.sleep(max(0.2, float(step_sec)))
    try:
        last = client.get_order(order_id)
    except Exception:
        pass
    st = str((last or {}).get("status") or "").upper()
    return st, last


def cancel_token_orders(client, token_id: str) -> Optional[dict[str, Any]]:
    if client is None:
        return None
    try:
        return client.cancel_market_orders(asset_id=str(token_id))
    except Exception as e:
        return {"error": str(e)}


def run_open(
    repo: str,
    slug: str,
    side: str,
    stake: float,
    execute: bool,
    profile: dict[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    cmd = [
        ".venv/bin/python",
        "src/live/pm_live_trade_runner.py",
        "--market-slug",
        slug,
        "--force-side",
        side,
        "--start-equity",
        "100",
        "--risk-frac",
        str(stake / 100.0),
        "--max-notional-usd",
        str(stake),
    ]
    if execute:
        cmd.append("--execute")
    env = open_execution_env(profile, os.environ.copy())
    p = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, env=env)
    out = (p.stdout or "") + "\n" + (p.stderr or "")
    return out, parse_json_objects(out)


def run_close(
    repo: str,
    slug: str,
    token_id: str,
    shares: float,
    execute: bool,
    close_order_type: str = "FAK",
    close_limit_price_val: float | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    cmd = [
        ".venv/bin/python",
        "src/live/pm_live_trade_runner.py",
        "--market-slug",
        slug,
        "--close-token-id",
        token_id,
        "--close-shares",
        f"{shares:.8f}",
    ]
    if close_limit_price_val is not None and close_limit_price_val > 0:
        cmd += ["--close-limit-price", f"{close_limit_price_val:.6f}"]
    if execute:
        cmd.append("--execute")
    env = os.environ.copy()
    env["PM_CLOSE_ORDER_TYPE"] = str(close_order_type or "FAK").upper()
    p = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, env=env)
    out = (p.stdout or "") + "\n" + (p.stderr or "")
    return out, parse_json_objects(out)


def default_repo_path() -> str:
    env_repo = os.environ.get("POLYBTC_REPO")
    if env_repo:
        return env_repo
    return str(Path(__file__).resolve().parents[3] / "pm-hl-conservative-plus-repo")


def default_runtime_dir() -> str:
    return str(Path(__file__).resolve().parents[1] / "runtime")


def default_config_path() -> str:
    return str(Path(__file__).resolve().parents[1] / "config" / "polybtc_profiles.yaml")


def load_profile(config_path: str, name: str) -> dict[str, Any]:
    cfg = load_config(config_path)
    errs = validate_config(cfg)
    if errs:
        raise SystemExit("invalid config:\n  - " + "\n  - ".join(errs))
    return get_profile(cfg, name)


def apply_cli_overrides(args: argparse.Namespace, profile: dict[str, Any]) -> argparse.Namespace:
    """CLI flags override YAML when provided; otherwise use profile values."""
    if args.threshold is None:
        args.threshold = float(profile["threshold_price"])
    if args.stake_usd is None:
        args.stake_usd = float(min(profile["stake_usd"], profile["max_notional_usd"]))
    sl = profile.get("stop_loss") or {}
    if args.stop_loss_pct is None:
        args.stop_loss_pct = float(sl.get("stop_loss_pct_from_entry", 0.25))
    if args.exit_before_sec is None:
        args.exit_before_sec = int(profile["exit_before_sec"])
    if args.min_entry_seconds_left is None:
        args.min_entry_seconds_left = int(profile["min_entry_seconds_left"])
    if args.entry_timeout_min is None:
        args.entry_timeout_min = 60
    if args.poll_sec is None:
        args.poll_sec = 5.0
    if args.max_close_slippage is None:
        # Do not dump below ~ half entry by default (floor still absolute 0.01).
        args.max_close_slippage = max(float(args.stop_loss_pct) + 0.10, 0.40)
    return args


def main() -> None:
    ap = argparse.ArgumentParser(description="PolyBTC Momentum session runner (gated)")
    ap.add_argument("--repo", default=default_repo_path())
    ap.add_argument("--config", default=default_config_path())
    ap.add_argument("--runtime-dir", default=os.environ.get("POLYBTC_RUNTIME_DIR") or default_runtime_dir())
    ap.add_argument(
        "--profile",
        choices=["conservative", "aggressive", "high_confidence"],
        default="conservative",
    )
    ap.add_argument("--threshold", type=float, default=None)
    ap.add_argument("--stake-usd", type=float, default=None)
    ap.add_argument("--stop-loss-pct", type=float, default=None, help="0.30 means -30%% from entry price")
    ap.add_argument("--exit-before-sec", type=int, default=None)
    ap.add_argument("--min-entry-seconds-left", type=int, default=None)
    ap.add_argument("--entry-timeout-min", type=int, default=None)
    ap.add_argument("--poll-sec", type=float, default=None)
    ap.add_argument("--close-retry-max", type=int, default=18)
    ap.add_argument("--close-retry-delay-sec", type=float, default=2.0)
    ap.add_argument(
        "--max-close-slippage",
        type=float,
        default=None,
        help="Max fraction of entry allowed as close slippage floor (default ~ stop+buffer)",
    )
    ap.add_argument(
        "--equity",
        type=float,
        default=float(os.environ.get("POLYBTC_EQUITY") or 200),
        help="Account equity for daily loss cap (guardrails)",
    )
    ap.add_argument(
        "--skip-btc-move",
        action="store_true",
        help="Disable Binance impulse check (NOT recommended for live)",
    )
    ap.add_argument(
        "--btc-move-usd",
        type=float,
        default=None,
        help="Override observed BTC move (USD signed close-open); otherwise fetch Binance 5m candle",
    )
    ap.add_argument("--execute", action="store_true", help="Place real orders (default: dry-run)")
    args = ap.parse_args()

    profile = load_profile(args.config, args.profile)
    # Apply CLI threshold override into a working profile copy used by preflight.
    args = apply_cli_overrides(args, profile)
    work_profile = dict(profile)
    work_profile["threshold_price"] = float(args.threshold)
    work_profile["stake_usd"] = float(args.stake_usd)
    work_profile["min_entry_seconds_left"] = int(args.min_entry_seconds_left)
    work_profile["exit_before_sec"] = int(args.exit_before_sec)
    if work_profile.get("stop_loss"):
        work_profile["stop_loss"] = dict(work_profile["stop_loss"])
        work_profile["stop_loss"]["stop_loss_pct_from_entry"] = float(args.stop_loss_pct)

    report: dict[str, Any] = {
        "started_at": ts_utc(),
        "params": {
            "profile": args.profile,
            "threshold": args.threshold,
            "stake_usd": args.stake_usd,
            "stop_loss_pct": args.stop_loss_pct,
            "exit_before_sec": args.exit_before_sec,
            "min_entry_seconds_left": args.min_entry_seconds_left,
            "entry_timeout_min": args.entry_timeout_min,
            "poll_sec": args.poll_sec,
            "close_retry_max": args.close_retry_max,
            "close_retry_delay_sec": args.close_retry_delay_sec,
            "max_close_slippage": args.max_close_slippage,
            "equity": args.equity,
            "execute": args.execute,
            "runtime_dir": args.runtime_dir,
            "config": args.config,
        },
        "attempts": [],
    }

    # Capital guardrails from today's runtime logs
    trades = load_runs_from_logs(args.runtime_dir, limit=500)
    pnls = pnls_for_today_from_trades(trades, today_utc())
    gstate = build_guard_state_from_pnls(pnls, today_utc())
    gcheck = check_guards(work_profile, gstate, account_equity=args.equity)
    report["guardrails"] = gcheck
    if not gcheck.get("allowed", False):
        report["finished_at"] = ts_utc()
        report["result"] = "blocked_by_guardrails"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    deadline = time.time() + args.entry_timeout_min * 60
    opened = None
    consecutive_api_errors = 0
    max_api_errors = int(work_profile.get("skip_if_dns_or_api_errors_consecutive", 3))
    confirm_tracker = ConfirmTracker(needed=int(work_profile.get("confirm_polls", 1)))
    report["params"]["confirm_polls"] = confirm_tracker.needed
    report["params"]["min_skew_gap"] = work_profile.get("min_skew_gap")
    report["params"]["btc_move_usd_max"] = work_profile.get("btc_move_usd_max")
    report["params"]["require_ev_gate"] = work_profile.get("require_ev_gate")
    report["params"]["min_edge"] = work_profile.get("min_edge")
    report["params"]["session_filter"] = work_profile.get("session_filter")

    while time.time() < deadline:
        try:
            m = resolve_active_current_5m_market()
            if not m:
                report["attempts"].append({"ts": ts_utc(), "status": "heartbeat_no_current_market"})
                time.sleep(args.poll_sec)
                continue

            g_up, g_dn, up_t, dn_t, slug, end_iso = market_side_prices(m)

            try:
                end_ts = dt.datetime.fromisoformat(end_iso.replace("Z", "+00:00")).timestamp()
                sec_left = max(0.0, end_ts - time.time())
            except Exception:
                report["attempts"].append({"ts": ts_utc(), "slug": slug, "status": "heartbeat_bad_market_end"})
                time.sleep(args.poll_sec)
                continue

            try:
                snap = clob_side_snapshot(up_t, dn_t)
                consecutive_api_errors = 0
            except Exception as e:
                consecutive_api_errors += 1
                report["attempts"].append(
                    {
                        "ts": ts_utc(),
                        "slug": slug,
                        "status": "skip_clob_unavailable",
                        "error": str(e),
                        "consecutive_api_errors": consecutive_api_errors,
                    }
                )
                if consecutive_api_errors >= max_api_errors:
                    report["finished_at"] = ts_utc()
                    report["result"] = "blocked_api_errors"
                    print(json.dumps(report, ensure_ascii=False, indent=2))
                    return
                time.sleep(args.poll_sec)
                continue

            if args.btc_move_usd is not None:
                btc_move = float(args.btc_move_usd)
            elif args.skip_btc_move:
                btc_move = float(work_profile.get("btc_move_usd_min", 70))
            else:
                btc_move = btc_move_usd_current_5m()
                if btc_move is None:
                    report["attempts"].append(
                        {"ts": ts_utc(), "slug": slug, "status": "skip_btc_move_unavailable"}
                    )
                    time.sleep(args.poll_sec)
                    continue

            # Pick top-ask notional for the stronger candidate side for liquidity check.
            up_ask = snap["up_ask"]
            dn_ask = snap["dn_ask"]
            top_notional = 0.0
            thr = float(args.threshold)
            cands = []
            if up_ask is not None and float(up_ask) >= thr:
                cands.append(("UP", float(up_ask), float(snap["up_ask_notional"] or 0)))
            if dn_ask is not None and float(dn_ask) >= thr:
                cands.append(("DOWN", float(dn_ask), float(snap["dn_ask_notional"] or 0)))
            if cands:
                _, _, top_notional = max(cands, key=lambda x: x[1])
            else:
                top_notional = max(
                    float(snap["up_ask_notional"] or 0),
                    float(snap["dn_ask_notional"] or 0),
                )

            spread = float(snap["min_spread"] if snap["min_spread"] is not None else 99.0)

            market = MarketSnapshot(
                seconds_left=float(sec_left),
                btc_move_usd=float(btc_move),
                up_ask=float(up_ask) if up_ask is not None else None,
                dn_ask=float(dn_ask) if dn_ask is not None else None,
                spread=spread,
                top_ask_notional_usd=float(top_notional),
                quote_age_sec=float(snap.get("quote_age_sec") or 0.0),
                hour_utc=int(now_utc().hour),
            )
            decision = evaluate(work_profile, market)
            confirmed, confirm_streak = confirm_tracker.update(decision)
            report["attempts"].append(
                {
                    "ts": ts_utc(),
                    "slug": slug,
                    "status": "preflight",
                    "gamma_up": g_up,
                    "gamma_down": g_dn,
                    "clob_up_ask": up_ask,
                    "clob_down_ask": dn_ask,
                    "seconds_left": sec_left,
                    "btc_move_usd": btc_move,
                    "spread": spread,
                    "top_ask_notional": top_notional,
                    "hour_utc": market.hour_utc,
                    "skew_gap": decision.skew_gap,
                    "estimated_win_prob": decision.estimated_win_prob,
                    "edge": decision.edge,
                    "preflight_ok": decision.ok,
                    "preflight_side": decision.side,
                    "preflight_reasons": decision.reasons,
                    "checks": decision.checks,
                    "confirm_streak": confirm_streak,
                    "confirm_needed": confirm_tracker.needed,
                    "confirm_ready": confirmed,
                }
            )

            if not decision.ok or decision.side is None or decision.entry_price is None:
                time.sleep(args.poll_sec)
                continue

            if not confirmed:
                report["attempts"].append(
                    {
                        "ts": ts_utc(),
                        "slug": slug,
                        "status": "await_confirm",
                        "side": decision.side,
                        "confirm_streak": confirm_streak,
                        "confirm_needed": confirm_tracker.needed,
                    }
                )
                time.sleep(args.poll_sec)
                continue

            side = decision.side
            stake = float(decision.stake_usd or args.stake_usd)
            out, objs = run_open(args.repo, slug, side, stake, args.execute, work_profile)
            post = None
            runner = None
            for o in objs:
                if isinstance(o, dict) and "order_post_result" in o:
                    runner = o
                    post = o.get("order_post_result") or {}

            if not args.execute:
                # Dry-run: record decision and exit without monitoring a position.
                report["dry_run_decision"] = {
                    "side": side,
                    "entry_price": decision.entry_price,
                    "stake_usd": stake,
                    "stop_loss_price": decision.stop_loss_price,
                    "hedge": decision.hedge,
                    "open_raw_tail": out[-2000:],
                }
                report["finished_at"] = ts_utc()
                report["result"] = "dry_run_go"
                print(json.dumps(report, ensure_ascii=False, indent=2))
                return

            if post and post.get("success") is True and str(post.get("status", "")).lower() == "matched":
                token_id = str(runner.get("token_id") or (up_t if side == "UP" else dn_t))
                shares = float(post.get("takingAmount") or 0)
                cost = float(post.get("makingAmount") or 0)
                entry_price = float(runner.get("entry_price") or decision.entry_price)
                opened = {
                    "opened_at": ts_utc(),
                    "market_slug": slug,
                    "market_end_iso": end_iso,
                    "side": side,
                    "token_id": token_id,
                    "entry_price": entry_price,
                    "shares": shares,
                    "cost_usdc": cost,
                    "open_order_id": post.get("orderID"),
                    "open_tx": (post.get("transactionsHashes") or [None])[0],
                }
                report["open_raw"] = out[-4000:]
                report["preflight_on_entry"] = {
                    "side": side,
                    "entry_price": decision.entry_price,
                    "stake_usd": stake,
                    "reasons": decision.reasons,
                    "checks": decision.checks,
                }
                break
            else:
                report["last_open_try"] = out[-2000:]
        except Exception as e:
            report["attempts"].append({"ts": ts_utc(), "status": "error", "error": str(e)})
        time.sleep(args.poll_sec)

    if not opened:
        report["finished_at"] = ts_utc()
        report["result"] = "no_entry_timeout"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    report["opened"] = opened

    end_ts = None
    try:
        end_ts = dt.datetime.fromisoformat(opened["market_end_iso"].replace("Z", "+00:00")).timestamp()
    except Exception:
        end_ts = time.time() + 300

    sl_price = stop_loss_price(opened["entry_price"], args.stop_loss_pct)
    report["stop_loss_price"] = sl_price
    exit_policy = merge_exit_policy(work_profile)
    report["exit_policy"] = exit_policy

    close_reason = None
    exit_ticks: list[dict[str, Any]] = []
    while True:
        now = time.time()
        sec_left = max(0.0, float(end_ts) - now)

        # Stop-loss / exit marks: CLOB best bid (executable exit), not Gamma mid.
        try:
            side_px = clob_best_bid(opened["token_id"])
        except Exception:
            side_px = None

        # Optional BTC reverse check for early-cut (best-effort; skip if feed down).
        btc_move_now: Optional[float] = None
        early_cfg = (exit_policy.get("early_cut") or {})
        if early_cfg.get("enabled", True) and early_cfg.get("on_btc_reverse", True):
            if args.btc_move_usd is not None:
                btc_move_now = float(args.btc_move_usd)
            elif not args.skip_btc_move:
                try:
                    btc_move_now = btc_move_usd_current_5m()
                except Exception:
                    btc_move_now = None

        decision_x = decide_exit(
            entry_price=float(opened["entry_price"]),
            best_bid=side_px,
            seconds_left=sec_left,
            stop_loss_px=float(sl_price),
            exit_before_sec=float(args.exit_before_sec),
            side=str(opened.get("side") or "UP"),
            btc_move_usd=btc_move_now,
            exit_policy=exit_policy,
        )
        tick = {
            "ts": ts_utc(),
            "seconds_left": round(sec_left, 2),
            "best_bid": side_px,
            "btc_move_usd": btc_move_now,
            "action": decision_x.action,
            "reason": decision_x.reason,
            "hold_to_resolve": decision_x.hold_to_resolve,
            "effective_exit_before_sec": decision_x.effective_exit_before_sec,
        }
        exit_ticks.append(tick)
        report["last_side_price"] = side_px
        report["last_check_at"] = ts_utc()
        report["last_exit_decision"] = tick

        if decision_x.action == "close":
            if decision_x.reason == "stop_loss":
                close_reason = f"stop_loss_{int(args.stop_loss_pct * 100)}pct"
            else:
                close_reason = decision_x.reason
            break
        time.sleep(args.poll_sec)

    report["exit_ticks"] = exit_ticks[-40:]  # cap log size

    close_debug: list[dict[str, Any]] = []
    close_obj: dict[str, Any] = {}
    out = ""
    fallback_used = None
    force_close_used = None
    client = auth_clob_client()

    for i in range(max(1, int(args.close_retry_max))):
        out, objs = run_close(
            args.repo,
            opened["market_slug"],
            opened["token_id"],
            opened["shares"],
            args.execute,
            close_order_type="FAK",
        )
        close_obj = objs[-1] if objs else {}
        post = close_obj.get("order_post_result") or {}
        status = str(post.get("status") or "").lower()
        skipped = str(close_obj.get("close_skipped") or "")
        close_debug.append(
            {
                "ts": ts_utc(),
                "attempt": i + 1,
                "order_type": "FAK",
                "status": status,
                "close_skipped": skipped,
            }
        )
        if post.get("success") is True and status == "matched":
            break

        if skipped == "zero_effective_shares":
            time.sleep(float(args.close_retry_delay_sec))
            continue

        txt = ((out or "") + "\n" + json.dumps(close_obj, ensure_ascii=False)).lower()
        if "no orders found to match with fak order" in txt:
            bb = None
            try:
                bb = clob_best_bid(opened["token_id"])
            except Exception:
                bb = None
            limit_px = close_limit_price(
                opened["entry_price"],
                bb,
                aggressive_offset=0.01,
                max_slippage_from_entry=float(args.max_close_slippage),
            )
            fallback_used = {"type": "GTC_LIMIT", "price": limit_px, "best_bid": bb}
            out2, objs2 = run_close(
                args.repo,
                opened["market_slug"],
                opened["token_id"],
                opened["shares"],
                args.execute,
                close_order_type="GTC",
                close_limit_price_val=limit_px,
            )
            close_obj2 = objs2[-1] if objs2 else {}
            post2 = close_obj2.get("order_post_result") or {}
            status2 = str(post2.get("status") or "").lower()
            close_debug.append(
                {
                    "ts": ts_utc(),
                    "attempt": i + 1,
                    "order_type": "GTC",
                    "status": status2,
                    "close_skipped": str(close_obj2.get("close_skipped") or ""),
                    "limit_price": limit_px,
                }
            )
            close_obj = close_obj2
            out = out2
            if post2.get("success") is True and status2 == "matched":
                break

            if post2.get("success") is True and status2 == "live":
                oid2 = str(post2.get("orderID") or "")
                st_upd, _ord_upd = poll_order_status(
                    client,
                    oid2,
                    wait_sec=min(8.0, max(2.0, float(args.close_retry_delay_sec) * 2)),
                    step_sec=1.0,
                )
                close_debug.append(
                    {
                        "ts": ts_utc(),
                        "attempt": i + 1,
                        "order_type": "GTC_POLL",
                        "status": st_upd.lower() if st_upd else "",
                        "order_id": oid2,
                    }
                )
                if st_upd == "MATCHED":
                    post2["status"] = "matched"
                    close_obj["order_post_result"] = post2
                    break

                cancel_info = cancel_token_orders(client, opened["token_id"])
                bb2 = None
                try:
                    bb2 = clob_best_bid(opened["token_id"])
                except Exception:
                    bb2 = None
                force_px = close_limit_price(
                    opened["entry_price"],
                    bb2,
                    aggressive_offset=0.02,
                    max_slippage_from_entry=float(args.max_close_slippage),
                )
                force_close_used = {
                    "type": "FORCE_GTC_LIMIT",
                    "price": force_px,
                    "cancel_info": cancel_info,
                    "best_bid": bb2,
                }
                out3, objs3 = run_close(
                    args.repo,
                    opened["market_slug"],
                    opened["token_id"],
                    opened["shares"],
                    args.execute,
                    close_order_type="GTC",
                    close_limit_price_val=force_px,
                )
                close_obj3 = objs3[-1] if objs3 else {}
                post3 = close_obj3.get("order_post_result") or {}
                status3 = str(post3.get("status") or "").lower()
                close_debug.append(
                    {
                        "ts": ts_utc(),
                        "attempt": i + 1,
                        "order_type": "FORCE_GTC",
                        "status": status3,
                        "close_skipped": str(close_obj3.get("close_skipped") or ""),
                        "limit_price": force_px,
                    }
                )
                close_obj = close_obj3
                out = out3
                if post3.get("success") is True and status3 == "matched":
                    break

        time.sleep(float(args.close_retry_delay_sec))

    post = close_obj.get("order_post_result") or {}
    post_status = str(post.get("status") or "").lower()
    close_usdc = float(post.get("takingAmount") or 0)
    closed = {
        "close_reason": close_reason,
        "closed_at": ts_utc(),
        "close_success": bool(post.get("success") is True and (post_status == "matched" or close_usdc > 0)),
        "close_status": post.get("status"),
        "close_order_id": post.get("orderID"),
        "close_tx": (post.get("transactionsHashes") or [None])[0],
        "close_shares": float(post.get("makingAmount") or 0),
        "close_usdc": close_usdc,
        "close_skipped": close_obj.get("close_skipped"),
    }
    report["close_debug"] = close_debug
    if fallback_used:
        report["close_fallback"] = fallback_used
    if force_close_used:
        report["close_force"] = force_close_used
    report["close_raw"] = out[-4000:]
    report["closed"] = closed

    pnl = None
    if closed["close_usdc"]:
        pnl = round(closed["close_usdc"] - opened["cost_usdc"], 6)
    report["realized_cashflow_pnl_usdc"] = pnl
    report["finished_at"] = ts_utc()
    report["result"] = "done"

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
