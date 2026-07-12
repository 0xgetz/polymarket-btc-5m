# Changelog

All notable changes to this project are documented here.

## [Unreleased]
### Added
- **Accuracy calibrator** (`scripts/polybtc_calibrate.py`): grid-search
  threshold / skew / impulse min-max against a CSV via the same preflight
  backtest path; ranks by expectancy with a soft min-trades floor.
- Expanded sample backtest CSV (+6 rows for weak skew / blow-off / aligned wins).
- `tests/test_calibrate.py` and BACKTESTING.md calibration section.

### Improved (signal quality / accuracy)
- **Signed BTC impulse** on the live path: Binance 5m candle returns
  `close - open` (not abs). Fixes `require_move_aligned` for DOWN entries.
- **`btc_move_usd_max`**: skip blow-off candles above a per-profile USD cap.
- **`min_skew_gap`**: market skew confirmation — chosen ask must beat the
  opposite side by at least this gap (implements checklist item “skew confirmation”).
- **`confirm_polls`**: anti-spike gate — same-side preflight GO must hold across
  N consecutive polls before entry (`ConfirmTracker` in preflight + live runner).
- Profile defaults: conservative (max $200, skew 0.18, confirm 2), aggressive
  (max $250, skew 0.12, confirm 1), high_confidence (max $160, skew 0.30, confirm 3).
- **Direction alignment** (`require_move_aligned`): only enter UP when BTC move is
  positive and DOWN when negative — blocks counter-impulse thrashing.
- **`high_confidence` profile**: threshold 0.82–0.92 band, harder impulse ($95),
  hard entry window, lower size/frequency. Aims for quality, not guaranteed 90% WR.
- **`max_entry_price`**: skip ultra-rich asks with almost no payout (e.g. 0.97).
- Preflight also supports per-profile `btc_move_usd_min` and `require_entry_window`.

### Fixed (audit / live safety)
- **Wire preflight + capital guardrails into the live runner** before any open order
  (time, BTC impulse via Binance 5m candle, spread, liquidity, threshold side).
- **Single profile source of truth**: live runner loads `config/polybtc_profiles.yaml`
  via `polybtc_config` (removed hardcoded live `PROFILES` dict).
- **Stop-loss mark uses CLOB best bid** (executable exit), not Gamma mid prices.
- **Close limit floor**: force/GTC close prices cannot dump below
  `entry * (1 - max_close_slippage)` (no more 0.01 fire-sale by default).
- **Open-order env no longer disables spread/liquidity** (`PM_MAX_SPREAD` /
  `PM_MIN_TOP_ASK_NOTIONAL_USD` now come from the profile).
- **`polybtc_ctl.sh` defaults to dry-run**; real money requires `--live` / `--execute`.
- **Graceful stop**: SIGTERM with wait before SIGKILL; lockfile + open-position warning.
- **Watcher** defaults to dry-run, uses a lockfile, and stops on guardrail block.
- Added `scripts/polybtc_live_safety.py` + tests; `requirements-live.txt` for CLOB client.
- **Plain monolithic session-runner** (`scripts/_psr_impl.py`, ~33KB) is the only
  implementation; removed zlib/base64 bootstrap (`session_runner.b64.*`),
  split source parts (`_psr_src_*`), and related repair helpers.
- examples/SKILL show dry-run-first paths.
- `polybtc_ctl.sh` / watcher resolve Python more robustly (`POLYBTC_PY`, trading
  venv, skill venv, then `python3`).

### Added
- **CSV historical backtester** (`scripts/polybtc_backtest.py`) that replays
  market snapshots through the same preflight logic used by live/dry-run tooling
  and reports win-rate, net PnL, expectancy, profit factor, max drawdown,
  side-level breakdowns, and optional per-trade detail.
- **EV gate for backtests** (`--ev-gate --min-edge`) that requires
  `estimated_win_prob - entry_price` to clear a configurable minimum edge before
  a simulated trade is included.
- **Sample backtest dataset** (`examples/polybtc_backtest_sample_data.csv`) for
  testing the CSV schema and CLI quickly.
- **Backtesting guide** (`BACKTESTING.md`) explaining the CSV schema,
  output fields, EV gate, and a practical paper-to-backtest workflow.
- **Backtester tests** (`tests/test_backtest.py`) covering signal replay,
  EV-gated skips, and `win` / `loss` outcome aliases.
- **Environment template** (`.env.example`) documenting safe local defaults for
  runtime path, profile, equity baseline, webhook, and runner overrides without
  committing secrets.
- **Dependabot configuration** (`.github/dependabot.yml`) for weekly Python and
  GitHub Actions dependency update pull requests.
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

### Changed
- Expanded `.gitignore` to ignore pytest/coverage artifacts while explicitly
  allowing `.env.example` to remain tracked.
- Added `ruff` to development dependencies so Python linting can be run locally
  with `ruff check scripts tests`.

### Notes
- Surfaced a latent config nuance: the entry-time gate
  (`min_entry_seconds_left`) and the hedge time window
  (`trigger_seconds_left_lte`) do not overlap, so the micro-hedge is modeled as
  a separate near-close action (`compute_hedge`) rather than part of the entry
  decision.
