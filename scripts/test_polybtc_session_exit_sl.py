#!/usr/bin/env python3
"""Canonical entrypoint (compat name). Implementation lives in polybtc_session_runner."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure scripts/ is importable when invoked as a file path.
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from polybtc_session_runner import main  # noqa: E402

if __name__ == "__main__":
    main()
