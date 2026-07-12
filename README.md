<div align="center">

<img src="assets/logo.png" alt="PolyBTC Momentum" width="220"/>

# PolyBTC Momentum Skill

**Open-source OpenClaw skill for BTC 5-minute Up/Down momentum trading on Polymarket**

[![CI](https://github.com/0xgetz/polymarket-btc-5m/actions/workflows/ci.yml/badge.svg)](https://github.com/0xgetz/polymarket-btc-5m/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12-blue)
![Shell](https://img.shields.io/badge/shell-bash-green)
![Platform](https://img.shields.io/badge/platform-OpenClaw-black)
![Market](https://img.shields.io/badge/market-Polymarket%20BTC%205m-6f42c1)
![Strategy](https://img.shields.io/badge/strategy-momentum--into--close-orange)
![License](https://img.shields.io/badge/license-MIT-blue)
[![Donasi Saweria](https://img.shields.io/badge/%E2%9D%A4%20Donasi-Saweria-ff5e00?style=for-the-badge)](https://saweria.co/0xgetz)

[**Repository**](https://github.com/0xgetz/polymarket-btc-5m)

</div>

---

## 🎬 Demo

### Live Trading Session (conservative profile)
<p align="center"><img src="assets/demo-trading.gif" alt="PolyBTC Momentum live trading session" width="820"/></p>

> Resolve BTC 5m market → confirm impulse + skew + edge → enter with momentum → managed exit before close.

### Status & PnL Report
<p align="center"><img src="assets/demo-report.gif" alt="PolyBTC Momentum status and report" width="820"/></p>

---

## Strategy (Momentum into Close)
This skill is a short-horizon **momentum-into-close** stack (not a reversal system):

1. Trade Polymarket BTC 5m Up/Down markets near expiry.
2. Prefer entries around **~120 seconds left** (tolerance / hard window configurable).
3. Require a **signed** BTC impulse on the active 5m candle (`close − open`), with optional **1m agreement** (anti-wick).
4. Follow market skew: stronger CLOB ask over threshold; optional `min_skew_gap` and `max_entry_price`.
5. Gate on **heuristic edge** (`est_win_prob − entry ≥ min_edge`) and optional UTC **session hours**.
6. Size with **fixed or edge-scaled** stake (profile caps), with optional **loss-streak soft size-down**.
7. Manage exit: hard stop on CLOB bid, **hold-to-resolve** when nearly certain, **early-cut** if underwater / BTC reverses near expiry, else time exit.
8. Optional micro-hedge on extreme near-close skew (e.g. 95/5).

Profiles live only in `config/polybtc_profiles.yaml`:

| Profile | Intent |
|---|---|
| `conservative` | Default live path: stricter filters, edge gate, session blocks, edge-scaled size |
| `aggressive` | Higher frequency / risk, looser edge & session |
| `high_confidence` | Selective mid-high threshold band, harder impulse, more confirm polls |
| `observe` | **Research only** — looser gates for `polybtc_live_logger` / dry-run; **not for live money** |

## 📊 Realistic Expectations — No Guaranteed Profit

This is a high-variance speculative strategy. **No setup can guarantee profit**,
and anyone promising a "99% win rate" is misleading you. The payoff is
asymmetric — you buy a side at price `p`, so your **break-even win-rate equals
`p`**: you must be right *more* than `p`% of the time just to avoid losing money.

| Entry price | Win payoff ($5 stake) | Loss | Break-even win-rate |
|---|---|---|---|
| 0.71 | +$2.04 | −$5.00 | **> 71%** |
| 0.90 | +$0.56 | −$5.00 | **> 90%** |
| 0.95 | +$0.26 | −$5.00 | **> 95%** |

At 0.71 a single loss erases ~2.4 wins. The realistic objective is a **measured,
positive edge with strict capital protection** — not guaranteed wins. Use the
analytics, edge, exit, and fill tools (see [Tooling & Validation](#-tooling--validation))
to verify real expectancy before sizing up.

## Repository Structure
- `SKILL.md` — skill definition and operating rules
- `CONTOUR.md` — canonical execution path + post-audit safety notes
- `BACKTESTING.md` — CSV historical backtest + calibrator guide
- `config/polybtc_profiles.yaml` — single source of truth for profiles / risk
- `scripts/` — runners, preflight, analytics, live logger, reports
  (`_psr_impl.py` is the live-session implementation)
- `examples/` — command examples + sample backtest CSV
- `assets/` — logo and demo GIFs
- `tests/` — pytest (config, preflight, edge, guardrails, analytics, dry-run,
  summary, live safety, backtest, calibrate, exit/fill reports, logger CSV)
- `.github/workflows/` — CI (lint, compile, config validation, tests)

## Deploy / Run
### Prerequisites
- OpenClaw environment (optional for pure Python tooling)
- Polymarket execution stack for **real orders** (e.g. `pm-hl-conservative-plus-repo`)
- Python 3.12+ venv: `pip install -r requirements.txt` (and `requirements-live.txt` for CLOB client)
- API credentials only outside this repo (via env / external `.env`)

### Quick Start
```bash
git clone https://github.com/0xgetz/polymarket-btc-5m.git
cd polymarket-btc-5m
pip install -r requirements.txt
```

Read:
- `SKILL.md`
- `config/polybtc_profiles.yaml`

**Observe-only** (no orders — good first step):
```bash
python scripts/polybtc_live_logger.py --profile observe --minutes 60 --poll-sec 5
# JSONL + CSV land in ./runtime/
```

Dry-run session runner (default — no orders):
```bash
python scripts/test_polybtc_session_exit_sl.py --profile conservative
# or:
scripts/polybtc_ctl.sh start --profile conservative
scripts/polybtc_ctl.sh start --profile high_confidence   # selective
```

Live only after validation (explicit flag required):
```bash
python scripts/test_polybtc_session_exit_sl.py --profile conservative --execute
scripts/polybtc_ctl.sh start --profile conservative --live
```

Unified skill control:
```bash
scripts/polybtc_ctl.sh start --profile conservative          # dry-run
scripts/polybtc_ctl.sh start --profile conservative --live   # real orders
scripts/polybtc_ctl.sh status
scripts/polybtc_ctl.sh report --limit 20
scripts/polybtc_ctl.sh stop   # SIGTERM first; may leave open positions if killed mid-trade
```

### Live safety (post-audit)

Defaults keep real money hard to enable by accident:

| Control | Behavior |
|---|---|
| **Default mode** | Dry-run (no orders). Live needs `--execute` / `polybtc_ctl.sh --live`. |
| **Preflight gate** | Time, **signed** BTC 5m impulse (+ max cap), optional **1m align**, quote age, spread, liquidity, threshold / `max_entry`, skew gap, multi-poll confirm, **EV gate**, **session hour** — before any open. |
| **Sizing** | Base stake + optional **edge-scale** + **loss-streak soft scale**, hard `max_notional_usd`. |
| **Capital guardrails** | Consecutive-loss kill switch, daily max-loss %, max trades/day. |
| **Profile source** | `config/polybtc_profiles.yaml` only (`polybtc_config`). |
| **Managed exit** | Stop on CLOB best bid; hold-to-resolve; early-cut; time exit (`decide_exit`). |
| **Close limit floor** | Force/GTC close cannot dump below `entry * (1 - max_close_slippage)`. |
| **Open-order env** | Spread / top-ask notional from profile (`PM_MAX_SPREAD`, `PM_MIN_TOP_ASK_NOTIONAL_USD`). |
| **Stop semantics** | `polybtc_ctl.sh stop`: SIGTERM → wait → SIGKILL; lockfile + open-position warning. |
| **Watcher** | `watch_polybtc_threshold_and_enter.sh` defaults dry-run; lockfile; stops on guardrail block. |

Helpers: `scripts/polybtc_live_safety.py` (unit-tested). Live CLOB deps: `requirements-live.txt`.

Runtime isolation:
- skill runtime dir: `./runtime`
- auth/env source (default): `<your-workspace>/pm-hl-conservative-plus-repo/.env`
- overrides: `POLYBTC_REPO`, `POLYBTC_ENV_FILE`, `POLYBTC_RUNNER`, `POLYBTC_RUNTIME_DIR`, `POLYBTC_PY`

Optional Docker:
```bash
scripts/polybtc_docker.sh up
scripts/polybtc_docker.sh status
scripts/polybtc_docker.sh down
```

## 🧪 Tooling & Validation

Most helpers are pure / deterministic (or public-API observe-only). Prefer them before live size-up.

### Config validator
```bash
pip install -r requirements.txt
python scripts/polybtc_config.py --validate
python scripts/polybtc_config.py --profile conservative --show
python scripts/polybtc_config.py --profile observe --show
```

### Preflight gate
GO / NO-GO engine: side, stake (edge + streak scaled), stop, hedge plan, checks, edge.

```bash
python scripts/polybtc_preflight.py --profile conservative \
  --seconds-left 118 --btc-move-usd 110 --btc-move-1m-usd 12 \
  --up-ask 0.74 --dn-ask 0.28 --spread 0.02 --top-ask-notional 50 \
  --hour-utc 14
```

Example GO (shape; values depend on profile):

```json
{
  "ok": true,
  "side": "UP",
  "entry_price": 0.74,
  "stake_usd": 6.25,
  "edge": 0.08,
  "estimated_win_prob": 0.82,
  "stake_scale": 1.25,
  "streak_scale": 1.0,
  "checks": {
    "session_hour": true,
    "time_to_close": true,
    "impulse_move": true,
    "impulse_max": true,
    "quote_fresh": true,
    "spread": true,
    "liquidity": true,
    "threshold_side": true,
    "move_aligned": true,
    "move_1m_aligned": true,
    "skew_confirm": true,
    "ev_gate": true
  }
}
```

### Live observe logger + CSV export (no orders)
```bash
python scripts/polybtc_live_logger.py --profile observe --minutes 60 --poll-sec 5
python scripts/polybtc_live_logger.py --export-jsonl runtime/polybtc_live_obs_....jsonl
```

### Accuracy calibrator (CSV grid search)
```bash
python scripts/polybtc_calibrate.py \
  --csv examples/polybtc_backtest_sample_data.csv \
  --profile conservative --top 10 --min-trades 2
```
Details: `BACKTESTING.md`.

### Backtest (CSV replay through preflight)
```bash
python scripts/polybtc_backtest.py \
  --csv examples/polybtc_backtest_sample_data.csv \
  --profile conservative
```

### Reports after paper/live
```bash
python scripts/polybtc_analytics.py --runtime-dir ./runtime --limit 200
python scripts/polybtc_exit_report.py --runtime-dir ./runtime --limit 200
python scripts/polybtc_fill_report.py --runtime-dir ./runtime --limit 200
python scripts/polybtc_daily_summary.py --profile conservative --equity 200
```

### Guardrails / edge math / dry-run
```bash
python scripts/polybtc_guardrails.py --profile conservative \
  --equity 200 --pnls=-5,-5,-5 --entry 0.71 --win-prob 0.80
python scripts/polybtc_edge.py --entry 0.71 --win-prob 0.80 --stake 5
python scripts/polybtc_edge.py --table
python scripts/polybtc_dryrun.py --profile conservative \
  --seconds-left 118 --btc-move-usd 84 --btc-move-1m-usd 10 \
  --up-ask 0.71 --dn-ask 0.29 --spread 0.02 --top-ask-notional 41 \
  --hour-utc 14 --market-slug btc-updown-5m-demo --outcome UP
```

### Tests & CI
```bash
pip install -r requirements-dev.txt
pytest -q
```
CI runs bash/Python syntax checks, config validation, and the full test suite.

## Execution Checklist (Before Live Trade)

1. **Market validity** — active BTC 5m slot, not already closed.
2. **Time window** — enough `min_entry_seconds_left`; prefer ~120s target window.
3. **Impulse** — signed 5m move ≥ `btc_move_usd_min`, ≤ `btc_move_usd_max` if set; side aligned.
4. **1m confirm** — if `require_1m_aligned`, current 1m candle agrees with side.
5. **Skew / price band** — threshold side, optional `min_skew_gap` and `max_entry_price`.
6. **EV gate** — heuristic edge ≥ `min_edge` when `require_ev_gate` is on.
7. **Session hour** — UTC hour not blocked (or on allow-list) if session filter enabled.
8. **Multi-poll** — `confirm_polls` same-side GO streak before open.
9. **Liquidity / spread / quote age** — pass profile execution safety.
10. **Sizing** — stake, edge-scale, loss-streak scale, max notional, daily caps.
11. **Exit policy** — stop-loss, hold-to-resolve, early-cut, `exit_before_sec`.
12. **Mode** — dry-run / observe logger first; `--execute` only after validation.

## Risk Controls Template
Defaults live in `config/polybtc_profiles.yaml` and are enforced on the live path:

- Per-trade stake base + **edge-scaled** size + **loss-streak soft size**
- Hard **max notional** / trade
- Daily max loss % and max trades / day
- Max consecutive losses (hard kill switch)
- Quote staleness, spread, and top-of-book liquidity guards
- Stop-loss on executable **CLOB best bid**
- Close limit floor (no 0.01 fire-sale by default)
- Managed exit: hold-to-resolve / early-cut / time exit
- Optional extreme-skew micro-hedge
- Session hour allow/block (UTC)
- Graceful process stop: SIGTERM → wait → SIGKILL

## 💖 Dukung Proyek Ini

Jika skill ini bermanfaat untuk trading atau riset Anda, dukung pengembangannya:

<div align="center">

[![Donasi di Saweria](https://img.shields.io/badge/%E2%9D%A4%20Donasi%20di%20Saweria-0xgetz-ff5e00?style=for-the-badge&logo=buymeacoffee&logoColor=white)](https://saweria.co/0xgetz)

</div>

Donasi membantu untuk:
- 🖥️ Biaya server & data feed untuk pengujian strategi
- ✨ Pengembangan fitur baru (filter impulse, multi-market, dashboard)
- 📚 Dokumentasi & contoh penggunaan yang lebih lengkap
- 🐛 Perbaikan bug dan pemeliharaan rutin

🔗 **https://saweria.co/0xgetz**

## Risk Notice
This repository is educational/operational infrastructure, not financial advice.
Use your own risk limits, daily loss caps, and capital controls.
**`observe` is for research logging only — do not enable live money on it.**

## Contributing
- Fork the repository
- Create a feature branch
- Commit changes
- Open a PR to `main`

PRs are welcome.
