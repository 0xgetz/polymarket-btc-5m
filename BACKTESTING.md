# Backtesting and EV Gate

Use the CSV backtester to replay historical BTC 5-minute market snapshots through the same preflight logic used by dry-run and live tooling. This is the safest first step before increasing real-money size.

## Why this matters

A strategy can look good in live observation but still have negative expectancy after spread, skew, liquidity, and losing streaks. Backtesting helps answer:

- How often does the strategy actually trade?
- What is the win rate after all preflight filters?
- Is net PnL positive after realistic entry prices?
- Which side performs better: UP or DOWN?
- Does an EV gate improve expectancy by skipping weak signals?

This does not guarantee future profit. It is a measurement tool for detecting whether the current rules deserve more paper/live testing.

## CSV format

Required columns:

```csv
market_id,timestamp,seconds_left,btc_move_usd,up_ask,dn_ask,spread,top_ask_notional_usd,quote_age_sec,outcome
```

Optional column:

```csv
estimated_win_prob
```

Recommended full schema:

```csv
market_id,timestamp,seconds_left,btc_move_usd,up_ask,dn_ask,spread,top_ask_notional_usd,quote_age_sec,outcome,estimated_win_prob
```

## Run the sample backtest

```bash
python scripts/polybtc_backtest.py \
  --csv examples/polybtc_backtest_sample_data.csv \
  --profile conservative
```

Show per-trade detail:

```bash
python scripts/polybtc_backtest.py \
  --csv examples/polybtc_backtest_sample_data.csv \
  --profile conservative \
  --trades
```

## Run with an EV gate

The EV gate requires `estimated_win_prob` and skips trades where:

```text
estimated_win_prob - entry_price < min_edge
```

Example: require at least 5 percentage points of edge over market price.

```bash
python scripts/polybtc_backtest.py \
  --csv examples/polybtc_backtest_sample_data.csv \
  --profile conservative \
  --ev-gate \
  --min-edge 0.05
```

If entry is `0.71`, a `--min-edge 0.05` gate requires `estimated_win_prob >= 0.76`.

## Output fields

The JSON report includes:

| Field | Meaning |
|---|---|
| `rows` | Total CSV rows processed. |
| `signals` | Rows that passed preflight before optional EV filtering. |
| `trades` | Trades included in the final simulation. |
| `wins` / `losses` | Resolved trade count. |
| `skipped_ev` | Signals skipped by the EV gate. |
| `win_rate` | Final simulated win rate. |
| `net_pnl_usd` | Total simulated PnL. |
| `expectancy_usd` | Average PnL per trade. |
| `profit_factor` | Gross profit divided by gross loss. |
| `max_drawdown_usd` | Max peak-to-trough drawdown over the simulated sequence. |
| `avg_entry_price` | Average selected entry price. |
| `avg_edge` | Average `estimated_win_prob - entry_price` for trades with estimates. |
| `by_side` | UP/DOWN performance split. |

## Practical workflow

1. Collect snapshots for several days in paper mode.
2. Export them to the CSV schema above.
3. Backtest with the current profile.
4. Backtest again with `--ev-gate --min-edge 0.03`, `0.05`, and `0.08`.
5. Compare expectancy, drawdown, and trade frequency.
6. Only consider increasing live size if the strategy remains positive out-of-sample.

## Next feature candidates

After enough data exists, the next high-impact additions are:

- automated snapshot collector,
- walk-forward parameter optimizer,
- slippage/depth-aware fill simulation,
- regime filters by volatility and time of day,
- dashboard for rolling PnL and kill-switch status.
