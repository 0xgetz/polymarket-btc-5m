# Example commands

Dry-run (safe validation):

```bash
.venv/bin/python scripts/test_polybtc_session_exit_sl.py --profile conservative
```

Real execution (conservative):

```bash
.venv/bin/python scripts/test_polybtc_session_exit_sl.py --profile conservative --execute
```

Real execution (aggressive):

```bash
.venv/bin/python scripts/test_polybtc_session_exit_sl.py --profile aggressive --execute
```
