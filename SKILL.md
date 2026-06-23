---
name: polybtc-momentum
description: Run and monitor BTC 5-minute Up/Down trading on Polymarket using momentum-near-close logic (time-left, BTC move, market skew), fixed/controlled sizing, optional micro-hedge, and one-shot or loop execution.
---

# BTC 5m Live

## Paths
- Main trading repo: `<your-workspace>/pm-hl-conservative-plus-repo` (or set `POLYBTC_REPO`)
- Core runner: `src/live/pm_live_trade_runner.py`
- Canonical skill runner: `scripts/test_polybtc_session_exit_sl.py`
- Skill control entrypoint: `scripts/polybtc_ctl.sh`
- Compatibility wrapper (deprecated): `scripts/run_polybtc_threshold_test.py`

## Strategy Alignment
Use this skill when the operator wants to execute a BTC 5m momentum strategy:
- Entry focus near event close (around 2 minutes left).
- Confirm meaningful BTC move in the interval (about $70-$100).
- Prefer direction supported by market skew.
- Enter with momentum, not against it.
- Optional small opposite hedge when skew becomes extreme.

## Operational Rules
- Default is dry-run unless `--execute` is set.
- Use controlled stake sizing (`--stake-usd`, profile caps).
- If both UP and DOWN satisfy threshold logic, choose the stronger side.
- Keep stop-loss and timing guards enabled in profile config.

## One-shot real test
From trading repo root:

```bash
.venv/bin/python scripts/test_polybtc_session_exit_sl.py --profile conservative --execute
```

Aggressive profile:

```bash
.venv/bin/python scripts/test_polybtc_session_exit_sl.py --profile aggressive --execute
```

Override profile params manually (example):

```bash
.venv/bin/python scripts/test_polybtc_session_exit_sl.py --profile conservative --stake-usd 5 --entry-timeout-min 90 --execute
```

## Strategy Profiles
- File: `config/polybtc_profiles.yaml`
- Presets: `conservative`, `aggressive`
- Includes entry/exit timing, quote staleness checks, spread/liquidity guards, hedge triggers, and risk caps.

## Hot Commands (chat-friendly)
Examples:
- `polybtc conservative start`
- `polybtc aggressive start`

Handlers:
- `scripts/polybtc_hot.sh [conservative|aggressive]`
- `scripts/polybtc_ctl.sh start --profile [conservative|aggressive]`
- `scripts/polybtc_ctl.sh status|stop|report|logs`
- completion summary utility: `scripts/polybtc_latest_report.py --mark`

Output:
- isolated skill runtime logs: `skills/polybtc-momentum/runtime/polybtc_<profile>_<UTCSTAMP>.log`

## Notes
- Canonical runner resolves current BTC 5m market slug (`btc-updown-5m-<bucket>`).
- Real order placement is delegated to `pm_live_trade_runner.py` with `--force-side` and `--max-notional-usd`.
- Keep BTC5m automation scoped to this skill contour (`polybtc_ctl.sh` + `skills/polybtc-momentum/runtime`) to avoid cross-skill interference.
- Keep all GitHub-facing docs and metadata in English.
