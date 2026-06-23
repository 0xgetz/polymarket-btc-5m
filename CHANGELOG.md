# Changelog

All notable changes to this project are documented here.

## [Unreleased]

### Added
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
