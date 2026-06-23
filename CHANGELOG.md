# Changelog

All notable changes to this project are documented here.

## [Unreleased]

### Added
- **Dry-run (paper trading) recorder** (`scripts/polybtc_dryrun.py`): runs the
  real preflight decision but places no order, recording simulated trades in the
  live log format so analytics/summary tools work identically. Validate the real
  edge before risking money.
- **Daily summary** (`scripts/polybtc_daily_summary.py` + cron wrapper
  `scripts/polybtc_daily_cron.sh`): aggregates a day's logs into win-rate, net
  PnL, profit factor, drawdown, and risk-limit flags; writes Markdown and can
  POST to a Slack/Discord/Telegram webhook. Automate via crontab.
- Test suite expanded to **60 cases** (added dry-run and daily-summary tests).
- **Trade analytics / log backtest** (`scripts/polybtc_analytics.py`): computes
  real win-rate, expectancy, profit factor, max drawdown, win/loss streaks, and
  per-side breakdown from runtime logs. Pure `compute_stats` engine + CLI.
- **Capital-protection guardrails** (`scripts/polybtc_guardrails.py`):
  consecutive-loss kill switch, daily max-loss cap, max-trades-per-day ceiling,
  and a positive-edge (EV) gate. Pure, deterministic, with a replay CLI.
- **Edge / break-even calculator** (`scripts/polybtc_edge.py`): payoff math,
  break-even win-rate, edge, and expected value as a library + CLI.
- New `risk_controls` block per profile (`max_consecutive_losses`, `min_edge`),
  validated by the config validator and exposed via `get_profile`.
- Expanded test suite to **48 cases** covering config, preflight, edge,
  guardrails, and analytics.
- **Config loader & validator** (`scripts/polybtc_config.py`): loads and
  validates `config/polybtc_profiles.yaml`, and resolves a single flattened
  profile (shared rules + strategy reference + per-profile settings) so the
  runner, preflight gate, and tests share one source of truth.
- **Preflight decision engine** (`scripts/polybtc_preflight.py`): a pure-logic
  implementation of the Execution Checklist returning a structured GO / NO-GO
  decision (chosen side, recommended stake, stop-loss price, optional
  near-close micro-hedge, and per-check pass/fail reasons). Usable as a library
  or CLI for dry-run gating.
- **Unit tests** (`tests/test_polybtc.py`): 21 pytest cases covering config
  validation and every preflight guard, side selection, sizing cap, stop-loss,
  and hedge logic.
- **Continuous Integration** (`.github/workflows/ci.yml`): runs bash syntax
  checks, Python compile checks, config validation, and the test suite on every
  push and pull request.
- `requirements.txt`, `requirements-dev.txt`, `.env.example`, `LICENSE` (MIT),
  and this changelog.

### Notes
- Surfaced a latent config nuance: the entry-time gate
  (`min_entry_seconds_left`) and the hedge time window
  (`trigger_seconds_left_lte`) do not overlap, so the micro-hedge is modeled as
  a separate near-close action (`compute_hedge`) rather than part of the entry
  decision.
