#!/usr/bin/env python3
"""PolyBTC session runner — readable source assembled from `_psr_src_*.txt`.

The implementation is plain Python split only so Git tooling can push
reviewable text files. This file concatenates the parts and executes them.
"""
from __future__ import annotations

import sys
from pathlib import Path

_DIR = Path(__file__).resolve().parent
_parts = sorted(_DIR.glob("_psr_src_*.txt"))
if not _parts:
    raise FileNotFoundError(f"No _psr_src_*.txt under {_DIR}")
_code = "".join(p.read_text(encoding="utf-8") for p in _parts)
_globals = {"__name__": "psr_impl", "__file__": str(_DIR / "_psr_impl_assembled.py")}
exec(compile(_code, str(_DIR / "_psr_impl_assembled.py"), "exec"), _globals)
main = _globals["main"]

if __name__ == "__main__":
    main()
