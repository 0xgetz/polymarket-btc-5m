#!/usr/bin/env python3
"""Gated live session runner — loads zlib payload from sibling .b64 files."""
from __future__ import annotations
import base64, importlib.util, zlib
from pathlib import Path

_DIR = Path(__file__).resolve().parent

def _load():
    target = _DIR / "_polybtc_session_runner_impl.py"
    if not target.exists() or target.stat().st_size < 1000:
        chunks = []
        for p in sorted(_DIR.glob("session_runner.b64.*")):
            chunks.append("".join(p.read_text().split()))
        target.write_bytes(zlib.decompress(base64.b64decode("".join(chunks))))
    spec = importlib.util.spec_from_file_location("psr_impl", target)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod

_mod = _load()
main = _mod.main

if __name__ == "__main__":
    main()
