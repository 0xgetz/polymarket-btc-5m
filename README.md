<div align="center">

<img src="assets/logo.png" alt="PolyBTC Momentum" width="220"/>

# PolyBTC Momentum Skill

**Open-source OpenClaw skill for BTC 5-minute Up/Down momentum trading on Polymarket**

![Python](https://img.shields.io/badge/python-3.12-blue)
![Shell](https://img.shields.io/badge/shell-bash-green)
![Platform](https://img.shields.io/badge/platform-OpenClaw-black)
![Market](https://img.shields.io/badge/market-Polymarket%20BTC%205m-6f42c1)
![Strategy](https://img.shields.io/badge/strategy-momentum--into--close-orange)
[![Donasi Saweria](https://img.shields.io/badge/%E2%9D%A4%20Donasi-Saweria-ff5e00?style=for-the-badge)](https://saweria.co/0xgetz)

[**Repository**](https://github.com/0xgetz/polymarket-btc-5m)

</div>

---

## 🎬 Demo

### Live Trading Session (conservative profile)
<p align="center"><img src="assets/demo-trading.gif" alt="PolyBTC Momentum live trading session" width="820"/></p>

> Resolve BTC 5m market → confirm move + skew → enter with momentum → managed exit before close.

### Status & PnL Report
<p align="center"><img src="assets/demo-report.gif" alt="PolyBTC Momentum status and report" width="820"/></p>

---

## Strategy (Momentum into Close)
This skill is aligned with a short-horizon momentum strategy:

1. Trade BTC 5m event markets near expiry.
2. Main entry window: around **2 minutes left**.
3. Confirm that BTC has already moved by about **$70-$100** in the active interval.
4. Check market skew (crowd positioning). If flow supports the move direction, enter **with** momentum.
5. Typical sizing: around **50% of trading allocation** (user-defined risk tolerance).
6. Optional micro-hedge when skew is extreme (for example, 95/5): place a small opposite position ($1-$2 equivalent) to reduce tail risk.

This is a momentum-following approach, not a reversal strategy.

## Repository Structure
- `SKILL.md` — skill definition and operating rules
- `config/` — profiles and risk parameters
- `scripts/` — runners/wrappers/hot commands
- `examples/` — practical command examples
- `assets/` — logo and demo GIFs

## Deploy / Run
### Prerequisites
- OpenClaw environment
- Polymarket execution stack available at:
  - `<your-workspace>/pm-hl-conservative-plus-repo`
- Python virtual env for runner scripts
- Valid API credentials configured outside this repository

### Quick Start
```bash
git clone https://github.com/0xgetz/polymarket-btc-5m.git
cd polymarket-btc-5m
```

Read:
- `SKILL.md`
- `config/polybtc_profiles.yaml`

Run a conservative real test (example):
```bash
.venv/bin/python scripts/test_polybtc_session_exit_sl.py --profile conservative --execute
```

Run aggressive profile:
```bash
.venv/bin/python scripts/test_polybtc_session_exit_sl.py --profile aggressive --execute
```

Unified skill control (recommended):
```bash
scripts/polybtc_ctl.sh start --profile conservative
scripts/polybtc_ctl.sh status
scripts/polybtc_ctl.sh report --limit 20
scripts/polybtc_ctl.sh stop
```

Runtime isolation:
- skill runtime dir: `./runtime`
- auth/env source (default): `<your-workspace>/pm-hl-conservative-plus-repo/.env`
- overrides: `POLYBTC_REPO`, `POLYBTC_ENV_FILE`, `POLYBTC_RUNNER`
- completion auto-report cron (topic 184): `polybtc-completion-autoreport-topic184`

Optional Docker isolation:
```bash
scripts/polybtc_docker.sh up
scripts/polybtc_docker.sh status
scripts/polybtc_docker.sh down
```

## Execution Checklist (Before Live Trade)
Use this quick pre-flight checklist before any real order:

1. **Market validity**
   - Confirm the BTC 5m market is active and not about to close unexpectedly.
2. **Time-to-close window**
   - Prefer entries around ~120 seconds left (with reasonable tolerance).
3. **Impulse confirmation**
   - Confirm the observed BTC move is meaningful (strategy reference: ~$70-$100).
4. **Skew confirmation**
   - Verify market skew supports the intended direction (do not fade strong momentum by default).
5. **Liquidity/spread checks**
   - Ensure spread and top-of-book notional pass your minimum thresholds.
6. **Sizing guardrails**
   - Validate stake, max notional, and daily loss limits before execution.
7. **Stop / exit controls**
   - Confirm stop-loss and `exit_before_sec` are configured.
8. **Execution mode**
   - Start in dry-run when changing parameters; switch to `--execute` only after validation.

## Risk Controls Template
Suggested baseline controls (adapt to your risk profile):

- **Per-trade risk cap**: 1%-15% of account equity (profile dependent)
- **Daily max loss**: hard stop at 10%-15%
- **Max trades/day**: fixed ceiling to avoid overtrading
- **Max notional/trade**: strict upper bound
- **Quote staleness guard**: skip if market data is stale
- **Spread guard**: skip when spread exceeds threshold
- **Liquidity guard**: skip when top ask/bid notional is too thin
- **Extreme skew hedge**: optional small opposite hedge in 95/5-type scenarios
- **Operational kill switch**: immediate stop on repeated API/DNS/execution failures

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

## Contributing
- Fork the repository
- Create a feature branch
- Commit changes
- Open a PR to `main`

PRs are welcome.
