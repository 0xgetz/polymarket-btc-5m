#!/usr/bin/env python3
"""Deprecated compatibility wrapper → canonical session runner."""

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
    # Forward all argv after this script name; default cwd = trading repo for venv.
    script = canonical_script()
    # Prefer same interpreter; runner may still call .venv for child order process.
    cmd = [sys.executable, script, *sys.argv[1:]]
    repo = os.environ.get("POLYBTC_REPO") or default_repo()
    # Runner itself lives in skill repo; cwd can stay skill root so imports work.
    p = subprocess.run(cmd, cwd=str(Path(script).resolve().parents[1]))
    return int(p.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
