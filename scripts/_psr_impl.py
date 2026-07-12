#!/usr/bin/env python3
"""Readable session runner — re-exports main from modular sources."""
from polybtc_session_loop import main

__all__ = ["main"]

if __name__ == "__main__":
    main()
