#!/usr/bin/env python3
"""Gated live session runner.

Load order (first existing file with size >= 1KB wins):
1. ``_psr_impl.py`` — readable source of truth (preferred for review/CI)
2. ``_polybtc_session_runner_impl.py`` — local cache from b64 expand
3. ``session_runner.b64.*`` — zlib+base64 bootstrap fallback
"""
from __future__ import annotations

import base64
import importlib.util
import zlib
from pathlib import Path

_DIR = Path(__file__).resolve().parent
_MIN_BYTES = 1000


def _exec_module(path: Path):
    spec = importlib.util.spec_from_file_location("psr_impl", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _expand_b64(target: Path) -> None:
    chunks: list[str] = []
    for p in sorted(_DIR.glob("session_runner.b64.*")):
        chunks.append("".join(p.read_text().split()))
    if not chunks:
        raise FileNotFoundError(
            "No session runner implementation found "
            f"(expected {_DIR / '_psr_impl.py'} or session_runner.b64.*)"
        )
    target.write_bytes(zlib.decompress(base64.b64decode("".join(chunks))))


def _load():
    preferred = _DIR / "_psr_impl.py"
    if preferred.exists() and preferred.stat().st_size >= _MIN_BYTES:
        return _exec_module(preferred)

    target = _DIR / "_polybtc_session_runner_impl.py"
    if not target.exists() or target.stat().st_size < _MIN_BYTES:
        _expand_b64(target)
    return _exec_module(target)


_mod = _load()
main = _mod.main

if __name__ == "__main__":
    main()
