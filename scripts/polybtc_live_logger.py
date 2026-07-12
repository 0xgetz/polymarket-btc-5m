#!/usr/bin/env python3
"""
PolyBTC Momentum — live observation logger (NO orders).

Polls Gamma + CLOB public book + Binance 5m/1m, runs the same preflight
``evaluate`` gate used by live trading, and appends JSONL snapshots to
``runtime/polybtc_live_obs_*.jsonl``. Safe for paper research without the
trading repo / private keys.

CLI:
    python scripts/polybtc_live_logger.py --profile conservative --minutes 15
    python scripts/polybtc_live_logger.py --profile high_confidence --poll-sec 5
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from polybtc_config import get_profile, load_config, validate_config  # noqa: E402
from polybtc_preflight import MarketSnapshot, evaluate  # noqa: E402

UTC = dt.timezone.utc
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
BINANCE = "https://api.binance.com/api/v3/klines"


def ts_utc() -> str:
    return dt.datetime.now(UTC).isoformat().replace("+00:00", "Z")


def bucket_5m(ts: int) -> int:
    return ts - (ts % 300)


def _parse_json_field(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return v
    return v


def btc_signed_move(interval: str, bucket_sec: int) -> Optional[float]:
    try:
        now = int(time.time())
        start_ms = (now - (now % bucket_sec)) * 1000
        r = requests.get(
            BINANCE,
            params={
                "symbol": "BTCUSDT",
                "interval": interval,
                "startTime": start_ms,
                "limit": 1,
            },
            timeout=10,
        )
        r.raise_for_status()
        arr = r.json()
        if not arr:
            return None
        return float(arr[0][4]) - float(arr[0][1])  # close - open
    except Exception:
        return None


def _best_bid_ask(book: Dict[str, Any]) -> Tuple[Optional[float], Optional[float], float]:
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    best_bid = best_ask = None
    ask_sz = 0.0
    for b in bids:
        try:
            p = float(b.get("price") if isinstance(b, dict) else b[0])
            if best_bid is None or p > best_bid:
                best_bid = p
        except (TypeError, ValueError, IndexError, AttributeError):
            continue
    for a in asks:
        try:
            if isinstance(a, dict):
                p = float(a.get("price"))
                s = float(a.get("size") or a.get("amount") or 0)
            else:
                p = float(a[0])
                s = float(a[1]) if len(a) > 1 else 0.0
            if best_ask is None or p < best_ask:
                best_ask = p
                ask_sz = s
        except (TypeError, ValueError, IndexError, AttributeError):
            continue
    notional = (best_ask or 0.0) * ask_sz
    return best_bid, best_ask, notional


def fetch_book(token_id: str) -> Optional[Dict[str, Any]]:
    try:
        r = requests.get(f"{CLOB}/book", params={"token_id": str(token_id)}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def resolve_market() -> Optional[Dict[str, Any]]:
    now = int(time.time())
    cur = bucket_5m(now)
    for slot in (cur, cur - 300, cur + 300):
        slug = f"btc-updown-5m-{slot}"
        try:
            r = requests.get(f"{GAMMA}/events", params={"slug": slug}, timeout=12)
            r.raise_for_status()
            arr = r.json()
        except Exception:
            continue
        if not arr:
            continue
        mkts = arr[0].get("markets") or []
        if not mkts:
            continue
        m = mkts[0]
        if m.get("closed") is True or m.get("active") is False:
            continue
        end_iso = str(m.get("endDate") or m.get("endDateIso") or "")
        try:
            end_ts = dt.datetime.fromisoformat(end_iso.replace("Z", "+00:00")).timestamp()
        except Exception:
            continue
        sec_left = end_ts - time.time()
        if sec_left <= 5:
            continue
        outcomes = _parse_json_field(m.get("outcomes")) or []
        tokens = _parse_json_field(m.get("clobTokenIds")) or []
        if len(tokens) < 2:
            continue
        up_i, dn_i = 0, 1
        labs = [str(x).lower() for x in outcomes[:2]] if isinstance(outcomes, list) else []
        if len(labs) >= 2 and ("up" in labs[1] or "yes" in labs[1]):
            up_i, dn_i = 1, 0
        return {
            "slug": slug,
            "end_iso": end_iso,
            "seconds_left": sec_left,
            "up_token": str(tokens[up_i]),
            "dn_token": str(tokens[dn_i]),
        }
    return None


def snapshot_once(profile: Dict[str, Any]) -> Dict[str, Any]:
    mkt = resolve_market()
    if not mkt:
        return {"ts": ts_utc(), "status": "no_active_market"}

    up_book = fetch_book(mkt["up_token"])
    dn_book = fetch_book(mkt["dn_token"])
    if not up_book or not dn_book:
        return {
            "ts": ts_utc(),
            "status": "clob_unavailable",
            "slug": mkt["slug"],
            "seconds_left": mkt["seconds_left"],
        }

    _, up_ask, up_n = _best_bid_ask(up_book)
    _, dn_ask, dn_n = _best_bid_ask(dn_book)
    up_bid, _, _ = _best_bid_ask(up_book)
    dn_bid, _, _ = _best_bid_ask(dn_book)

    spreads: List[float] = []
    if up_ask is not None and up_bid is not None:
        spreads.append(max(0.0, up_ask - up_bid))
    if dn_ask is not None and dn_bid is not None:
        spreads.append(max(0.0, dn_ask - dn_bid))
    spread = min(spreads) if spreads else 99.0

    thr = float(profile["threshold_price"])
    cands = []
    if up_ask is not None and up_ask >= thr:
        cands.append(("UP", up_ask, up_n))
    if dn_ask is not None and dn_ask >= thr:
        cands.append(("DOWN", dn_ask, dn_n))
    top_n = max(cands, key=lambda x: x[1])[2] if cands else max(up_n, dn_n)

    btc5 = btc_signed_move("5m", 300)
    btc1 = btc_signed_move("1m", 60)
    if btc5 is None:
        return {
            "ts": ts_utc(),
            "status": "btc_move_unavailable",
            "slug": mkt["slug"],
            "seconds_left": mkt["seconds_left"],
        }

    # Recompute seconds_left fresh
    try:
        end_ts = dt.datetime.fromisoformat(mkt["end_iso"].replace("Z", "+00:00")).timestamp()
        sec_left = max(0.0, end_ts - time.time())
    except Exception:
        sec_left = float(mkt["seconds_left"])

    market = MarketSnapshot(
        seconds_left=sec_left,
        btc_move_usd=float(btc5),
        up_ask=up_ask,
        dn_ask=dn_ask,
        spread=float(spread),
        top_ask_notional_usd=float(top_n),
        quote_age_sec=0.0,
        hour_utc=int(dt.datetime.now(UTC).hour),
        btc_move_1m_usd=float(btc1) if btc1 is not None else None,
    )
    decision = evaluate(profile, market)
    return {
        "ts": ts_utc(),
        "status": "obs",
        "slug": mkt["slug"],
        "seconds_left": round(sec_left, 2),
        "hour_utc": market.hour_utc,
        "btc_move_usd": btc5,
        "btc_move_1m_usd": btc1,
        "up_ask": up_ask,
        "dn_ask": dn_ask,
        "up_bid": up_bid,
        "dn_bid": dn_bid,
        "spread": spread,
        "top_ask_notional": top_n,
        "preflight_ok": decision.ok,
        "side": decision.side,
        "entry_price": decision.entry_price,
        "stake_usd": decision.stake_usd,
        "stake_scale": decision.stake_scale,
        "edge": decision.edge,
        "estimated_win_prob": decision.estimated_win_prob,
        "skew_gap": decision.skew_gap,
        "checks": decision.checks,
        "reasons": decision.reasons,
    }


_CSV_FIELDS = [
    "market_id",
    "timestamp",
    "seconds_left",
    "btc_move_usd",
    "btc_move_1m_usd",
    "up_ask",
    "dn_ask",
    "spread",
    "top_ask_notional_usd",
    "quote_age_sec",
    "hour_utc",
    "preflight_ok",
    "side",
    "entry_price",
    "edge",
    "estimated_win_prob",
    "stake_usd",
]


def row_to_csv_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    """Map an observation row to backtest-friendly CSV columns."""
    return {
        "market_id": row.get("slug") or "",
        "timestamp": row.get("ts") or "",
        "seconds_left": row.get("seconds_left"),
        "btc_move_usd": row.get("btc_move_usd"),
        "btc_move_1m_usd": row.get("btc_move_1m_usd"),
        "up_ask": row.get("up_ask"),
        "dn_ask": row.get("dn_ask"),
        "spread": row.get("spread"),
        "top_ask_notional_usd": row.get("top_ask_notional"),
        "quote_age_sec": 0.0,
        "hour_utc": row.get("hour_utc"),
        "preflight_ok": row.get("preflight_ok"),
        "side": row.get("side") or "",
        "entry_price": row.get("entry_price"),
        "edge": row.get("edge"),
        "estimated_win_prob": row.get("estimated_win_prob"),
        "stake_usd": row.get("stake_usd"),
    }


def export_jsonl_to_csv(jsonl_path: Path, csv_path: Path) -> int:
    """Write CSV from JSONL observations. Returns row count."""
    n = 0
    with open(jsonl_path, "r", encoding="utf-8") as fh, open(
        csv_path, "w", encoding="utf-8", newline=""
    ) as out:
        writer = csv.DictWriter(out, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("status") not in (None, "obs") and row.get("status") != "obs":
                # Keep only market observations
                if row.get("status") != "obs":
                    continue
            if row.get("status") == "obs" or (
                row.get("up_ask") is not None and row.get("btc_move_usd") is not None
            ):
                writer.writerow(row_to_csv_dict(row))
                n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description="PolyBTC live observation logger (no orders)")
    ap.add_argument(
        "--profile",
        default="observe",
        help="profile name (default: observe — looser research gates)",
    )
    ap.add_argument("--config", default=None)
    ap.add_argument("--poll-sec", type=float, default=5.0)
    ap.add_argument("--minutes", type=float, default=10.0, help="how long to log")
    ap.add_argument(
        "--runtime-dir",
        default=str(Path(__file__).resolve().parents[1] / "runtime"),
    )
    ap.add_argument(
        "--once",
        action="store_true",
        help="single snapshot then exit",
    )
    ap.add_argument(
        "--export-csv",
        action="store_true",
        default=True,
        help="write companion CSV for backtest/calibrate (default: on)",
    )
    ap.add_argument(
        "--no-export-csv",
        action="store_true",
        help="disable CSV export",
    )
    ap.add_argument(
        "--export-jsonl",
        default=None,
        help="export an existing JSONL file to CSV and exit (no live poll)",
    )
    args = ap.parse_args()

    if args.export_jsonl:
        src = Path(args.export_jsonl)
        if not src.is_file():
            print(f"ERROR: not found: {src}", file=sys.stderr)
            return 2
        dest = src.with_suffix(".csv")
        n = export_jsonl_to_csv(src, dest)
        print(json.dumps({"exported_rows": n, "csv": str(dest)}, indent=2))
        return 0

    cfg = load_config(args.config)
    errs = validate_config(cfg)
    if errs:
        print("INVALID config:", *errs, sep="\n  - ", file=sys.stderr)
        return 2
    if args.profile not in cfg.get("profiles", {}):
        print(
            f"ERROR: unknown profile '{args.profile}'; "
            f"available: {sorted(cfg.get('profiles', {}))}",
            file=sys.stderr,
        )
        return 2
    profile = get_profile(cfg, args.profile)

    runtime = Path(args.runtime_dir)
    runtime.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = runtime / f"polybtc_live_obs_{args.profile}_{stamp}.jsonl"
    csv_path = runtime / f"polybtc_live_obs_{args.profile}_{stamp}.csv"
    latest = runtime / "latest_obs.jsonl"
    # symlink-ish: also write path pointer
    (runtime / "latest_obs.path").write_text(str(out_path) + "\n", encoding="utf-8")

    deadline = time.time() + (0 if args.once else max(0.0, args.minutes) * 60.0)
    n = 0
    n_go = 0
    do_csv = bool(args.export_csv) and not bool(args.no_export_csv)
    print(
        json.dumps(
            {
                "started_at": ts_utc(),
                "profile": args.profile,
                "poll_sec": args.poll_sec,
                "minutes": args.minutes,
                "out": str(out_path),
                "csv": str(csv_path) if do_csv else None,
                "mode": "observe_only_no_orders",
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    csv_fh = None
    csv_writer = None
    if do_csv:
        csv_fh = open(csv_path, "w", encoding="utf-8", newline="")
        csv_writer = csv.DictWriter(csv_fh, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        csv_writer.writeheader()
        csv_fh.flush()

    try:
        with open(out_path, "a", encoding="utf-8") as fh:
            with open(latest, "a", encoding="utf-8") as latest_fh:
                while True:
                    row = snapshot_once(profile)
                    line = json.dumps(row, ensure_ascii=False)
                    fh.write(line + "\n")
                    fh.flush()
                    latest_fh.write(line + "\n")
                    latest_fh.flush()
                    if csv_writer is not None and row.get("status") == "obs":
                        csv_writer.writerow(row_to_csv_dict(row))
                        csv_fh.flush()
                    n += 1
                    if row.get("preflight_ok"):
                        n_go += 1
                    print(line, flush=True)
                    if args.once or time.time() >= deadline:
                        break
                    time.sleep(max(1.0, float(args.poll_sec)))
    finally:
        if csv_fh is not None:
            csv_fh.close()

    summary = {
        "finished_at": ts_utc(),
        "snapshots": n,
        "preflight_go": n_go,
        "out": str(out_path),
        "csv": str(csv_path) if do_csv else None,
    }
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
