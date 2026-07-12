#!/usr/bin/env python3
"""Session runner: open/close and profile loading."""
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

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from polybtc_analytics import load_runs_from_logs  # noqa: E402
from polybtc_config import get_profile, load_config, validate_config  # noqa: E402
from polybtc_guardrails import check_guards  # noqa: E402
from polybtc_live_safety import (  # noqa: E402
    build_guard_state_from_pnls,
    close_limit_price,
    open_execution_env,
    pnls_for_today_from_trades,
    stop_loss_price,
    today_utc,
)
from polybtc_preflight import MarketSnapshot, evaluate  # noqa: E402

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.constants import POLYGON
    from py_clob_client.clob_types import ApiCreds
except ImportError:  # pragma: no cover
    ClobClient = None  # type: ignore
    POLYGON = 137
    ApiCreds = None  # type: ignore

UTC = dt.timezone.utc

from polybtc_session_market import (  # noqa: E402
    auth_clob_client,
    cancel_token_orders,
    clob_best_bid,
    parse_json_objects,
    poll_order_status,
)
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
