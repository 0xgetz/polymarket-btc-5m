#!/usr/bin/env python3
"""
Deprecated compatibility wrapper.

Canonical BTC 5m runner is: test_polybtc_session_exit_sl.py
This wrapper keeps old command paths working but routes execution
through the canonical script to avoid duplicated strategy logic.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def default_repo() -> str:
    env_repo = os.environ.get("POLYBTC_REPO")
    if env_repo:
        return env_repo
    return str(Path(__file__).resolve().parents[3] / "pm-hl-conservative-plus-repo")


def canonical_script() -> str:
    return str(Path(__file__).resolve().with_name("test_polybtc_session_exit_sl.py"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.70)
    ap.add_argument("--stake-usd", type=float, default=4.0)
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--repo", default=default_repo())
    ap.add_argument("--profile", default="conservative")
    ap.add_argument("--entry-timeout-min", type=int, default=8)
    ap.add_argument("--poll-sec", type=float, default=2.0)
    args = ap.parse_args()

    script = canonical_script()
    cmd = [
        ".venv/bin/python",
        script,
        "--profile",
        str(args.profile),
        "--threshold",
        str(args.threshold),
        "--stake-usd",
        str(args.stake_usd),
        "--entry-timeout-min",
        str(args.entry_timeout_min),
        "--poll-sec",
        str(args.poll_sec),
    ]
    if args.execute:
        cmd.append("--execute")

    p = subprocess.run(cmd, cwd=args.repo)
    return int(p.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
