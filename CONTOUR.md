# BTC 5m Skill Contour (single source of truth)

## Canonical execution path
- Strategy runner (canonical):
  - `scripts/test_polybtc_session_exit_sl.py`
- Unified control entrypoint:
  - `scripts/polybtc_ctl.sh` (`start|status|stop|report|logs`)
- Compatibility wrapper (deprecated path, forwards to canonical):
  - `scripts/run_polybtc_threshold_test.py`
- Chat/start helper:
  - `scripts/polybtc_hot.sh`
- Watch helper:
  - `scripts/watch_polybtc_threshold_and_enter.sh`
- PnL/report utility:
  - `scripts/polybtc_report.py`
- Latest-run completion reporter:
  - `scripts/polybtc_latest_report.py`
- Optional docker control:
  - `scripts/polybtc_docker.sh`

## External dependency boundary
- Order placement/close engine is delegated to:
  - `<your-workspace>/pm-hl-conservative-plus-repo/src/live/pm_live_trade_runner.py`
- Auth source:
  - `<your-workspace>/pm-hl-conservative-plus-repo/.env` (or `POLYBTC_ENV_FILE`)

## Runtime artifacts
- Primary runtime dir (skill-isolated):
  - `skills/polybtc-momentum/runtime`
- BTC 5m run logs follow `polybtc_*` naming.

## Isolation guidance
- Keep BTC 5m cron/checkers scoped to this skill naming (`polybtc-*`).
- Avoid creating generic watchers in unrelated topics/chats.
- Keep all new BTC 5m automation pointing to canonical runner only.
- Active completion cron in this contour:
  - `polybtc-completion-autoreport-topic184` (`36d3b9e6-4638-4e93-80f6-abb268ebbe57`)

## Safety (post-audit)
- `polybtc_ctl.sh start` is dry-run unless `--live`.
- Live runner gates via preflight + guardrails; YAML is the only profile source.
- Canonical runner impl: `scripts/_psr_impl.py` (readable); `session_runner.b64.*` is bootstrap fallback only.
- Entry points: `scripts/test_polybtc_session_exit_sl.py` → `polybtc_session_runner.main`.
