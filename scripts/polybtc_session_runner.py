#!/usr/bin/env python3
"""Gated live session runner entrypoint.

Prefers readable ``_psr_impl.py`` + ``_psr_src_*.txt``.
Falls back to ``session_runner.b64.*`` zlib bootstrap if source parts are missing.
"""
from __future__ import annotations

import base64
import importlib.util
import sys
import zlib
from pathlib import Path

_DIR = Path(__file__).resolve().parent


def _exec_path(path: Path):
    if str(_DIR) not in sys.path:
        sys.path.insert(0, str(_DIR))
    spec = importlib.util.spec_from_file_location("psr_impl", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_readable():
    impl = _DIR / "_psr_impl.py"
    parts = sorted(_DIR.glob("_psr_src_*.txt"))
    if impl.exists() and parts:
        return _exec_path(impl)
    return None


def _repair_b64_part(text: str, name: str) -> str:
    """Repair known transport corruptions in bootstrap parts if present."""
    if name.endswith("b64.1") and len(text) == 3807:
        # Three single-char corruptions observed on one remote push.
        chars = list(text)
        if chars[2903:2905] == ["L", "S"]:
            chars[2903], chars[2904] = "U", "s"
        if chars[3092] == "V":
            chars[3092] = "X"
        return "".join(chars)
    return text


def _load_b64():
    target = _DIR / "_polybtc_session_runner_impl.py"
    if not target.exists() or target.stat().st_size < 1000:
        chunks = []
        for p in sorted(_DIR.glob("session_runner.b64.*")):
            text = _repair_b64_part(p.read_text(encoding="utf-8"), p.name)
            chunks.append("".join(text.split()))
        if not chunks:
            raise FileNotFoundError(
                "No session runner source found "
                "(need scripts/_psr_src_*.txt + _psr_impl.py or session_runner.b64.*)"
            )
        target.write_bytes(zlib.decompress(base64.b64decode("".join(chunks))))
    return _exec_path(target)


def _load():
    mod = _load_readable()
    if mod is not None:
        return mod
    return _load_b64()


_mod = _load()
main = _mod.main

if __name__ == "__main__":
    main()
