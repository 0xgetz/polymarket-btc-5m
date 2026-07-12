#!/usr/bin/env python3
"""Gated live session runner entrypoint.

Loads the readable implementation from ``_psr_impl.py`` (source of truth).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_DIR = Path(__file__).resolve().parent
_IMPL = _DIR / "_psr_impl.py"


def _load():
    if not _IMPL.exists():
        raise FileNotFoundError(
            f"Missing session runner implementation: {_IMPL}\n"
            "Expected scripts/_psr_impl.py to be present in the repository."
        )
    spec = importlib.util.spec_from_file_location("psr_impl", _IMPL)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {_IMPL}")
    mod = importlib.util.module_from_spec(spec)
    # Ensure scripts dir is importable for modular deps.
    import sys
    if str(_DIR) not in sys.path:
        sys.path.insert(0, str(_DIR))
    spec.loader.exec_module(mod)
    return mod


_mod = _load()
main = _mod.main

if __name__ == "__main__":
    main()
