#!/usr/bin/env bash
# PolyBTC Momentum — daily summary cron wrapper.
#
# Runs the daily summary for a given (default: yesterday UTC) date, writes a
# Markdown file under runtime/daily/, and optionally POSTs to a webhook.
#
# Example crontab entry (run every day at 00:10 UTC for the previous day):
#   10 0 * * * /path/to/polymarket-btc-5m/scripts/polybtc_daily_cron.sh >> /tmp/polybtc_daily.log 2>&1
#
# Optional environment overrides:
#   POLYBTC_PROFILE   profile name for risk context (default: conservative)
#   POLYBTC_EQUITY    account equity for daily-loss-cap context
#   POLYBTC_WEBHOOK   Slack/Discord/Telegram-compatible webhook URL
#   POLYBTC_PY        python interpreter (default: python3)
#   POLYBTC_DATE      override date (YYYY-MM-DD); default = yesterday UTC
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNTIME_DIR="$SKILL_ROOT/runtime"
DAILY_DIR="$RUNTIME_DIR/daily"
mkdir -p "$DAILY_DIR"

PY="${POLYBTC_PY:-python3}"
PROFILE="${POLYBTC_PROFILE:-conservative}"
DATE="${POLYBTC_DATE:-$(date -u -d 'yesterday' +%F 2>/dev/null || date -u -v-1d +%F)}"

ARGS=(
  "$SCRIPT_DIR/polybtc_daily_summary.py"
  --runtime-dir "$RUNTIME_DIR"
  --date "$DATE"
  --profile "$PROFILE"
  --out "$DAILY_DIR"
)
[ -n "${POLYBTC_EQUITY:-}" ] && ARGS+=(--equity "$POLYBTC_EQUITY")
[ -n "${POLYBTC_WEBHOOK:-}" ] && ARGS+=(--webhook "$POLYBTC_WEBHOOK")

echo "[$(date -u +%FT%TZ)] polybtc daily summary for $DATE (profile=$PROFILE)"
"$PY" "${ARGS[@]}"
