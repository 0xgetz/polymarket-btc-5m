#!/usr/bin/env python3
"""Deprecated compatibility wrapper → canonical session runner."""

import subprocess
import sys
from pathlib import Path


def canonical_script() -> str:
    return str(Path(__file__).resolve().with_name("test_polybtc_session_exit_sl.py"))


def main() -> int:
    # Forward all argv after this script name.
    script = canonical_script()
    # Prefer same interpreter; runner may still call .venv for child order process.
    cmd = [sys.executable, script, *sys.argv[1:]]
    # Runner lives in skill repo; cwd = skill root so sibling imports work.
    p = subprocess.run(cmd, cwd=str(Path(script).resolve().parents[1]))
    return int(p.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
