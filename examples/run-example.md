# Example commands

## Dry-run first (default — no orders)

```bash
# Canonical session entrypoint
.venv/bin/python scripts/test_polybtc_session_exit_sl.py --profile conservative

# Unified control (recommended)
scripts/polybtc_ctl.sh start --profile conservative
scripts/polybtc_ctl.sh status
scripts/polybtc_ctl.sh report --limit 20
scripts/polybtc_ctl.sh stop
```

## Live only after validation

Real placement requires an **explicit** flag. Do not use live mode until
preflight, guardrails, and paper/dry-run results look acceptable.

```bash
.venv/bin/python scripts/test_polybtc_session_exit_sl.py --profile conservative --execute
scripts/polybtc_ctl.sh start --profile conservative --live

# Aggressive profile (higher risk caps)
.venv/bin/python scripts/test_polybtc_session_exit_sl.py --profile aggressive --execute
scripts/polybtc_ctl.sh start --profile aggressive --live
```

## Safety reminders

- Profiles come only from `config/polybtc_profiles.yaml`.
- Live path runs preflight + capital guardrails **before** any open order.
- `polybtc_ctl.sh stop` sends SIGTERM first; open positions may remain if killed mid-trade.
- Watcher is also dry-run by default: pass `--live` as the 5th arg only when intentional.

```bash
# dry-run watch
scripts/watch_polybtc_threshold_and_enter.sh 0.75 4 20 180

# live watch (real orders)
scripts/watch_polybtc_threshold_and_enter.sh 0.75 4 20 180 --live
```
