#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_ROOT="$(cd "$SKILL_ROOT/../.." && pwd)"
REPO="${POLYBTC_REPO:-$WORKSPACE_ROOT/pm-hl-conservative-plus-repo}"
PY="$SCRIPT_DIR/run_polybtc_threshold_test.py"
RUNTIME_DIR="${POLYBTC_RUNTIME_DIR:-$SKILL_ROOT/runtime}"
LOG="$RUNTIME_DIR/polybtc_threshold_watch.log"
STATE="$RUNTIME_DIR/polybtc_threshold_watch.state"
LOCK="$RUNTIME_DIR/polybtc_threshold_watch.lock"

THRESHOLD="${1:-0.75}"
STAKE="${2:-4}"
SLEEP_SEC="${3:-20}"
MAX_MIN="${4:-180}"
LIVE=0
if [[ "${5:-}" == "--live" || "${POLYBTC_LIVE:-}" == "1" ]]; then
  LIVE=1
fi

mkdir -p "$RUNTIME_DIR"

if [[ -f "$LOCK" ]]; then
  old="$(cat "$LOCK" 2>/dev/null || true)"
  if [[ -n "$old" ]] && ps -p "$old" >/dev/null 2>&1; then
    echo "already_watching pid=$old"
    exit 0
  fi
fi
echo $$ >"$LOCK"
trap 'rm -f "$LOCK"' EXIT

start_ts=$(date +%s)
end_ts=$((start_ts + MAX_MIN*60))

mode_label="dry-run"
exec_flag=()
if [[ "$LIVE" -eq 1 ]]; then
  mode_label="LIVE"
  exec_flag=(--execute)
  echo "WARNING: watcher in LIVE mode" >&2
fi

echo "[$(date -u +%FT%TZ)] start watch mode=$mode_label threshold=$THRESHOLD stake=$STAKE sleep=$SLEEP_SEC max_min=$MAX_MIN" | tee -a "$LOG"

while true; do
  now=$(date +%s)
  if [ "$now" -ge "$end_ts" ]; then
    echo "[$(date -u +%FT%TZ)] timeout reached, stop" | tee -a "$LOG"
    exit 0
  fi

  # Single attempt per cycle with short entry timeout to avoid nested long loops.
  set +e
  out=$(cd "$REPO" && .venv/bin/python "$PY" \
    --profile conservative \
    --threshold "$THRESHOLD" \
    --stake-usd "$STAKE" \
    --entry-timeout-min 2 \
    --poll-sec 2 \
    "${exec_flag[@]}" 2>&1)
  rc=$?
  set -e
  echo "$out" >> "$LOG"

  if echo "$out" | grep -qE '"result": "(done|dry_run_go)"'; then
    echo "[$(date -u +%FT%TZ)] entry decision completed (rc=$rc), stopping watcher" | tee -a "$LOG"
    echo "entered_at=$(date -u +%FT%TZ)" > "$STATE"
    exit 0
  fi
  if echo "$out" | grep -q '"result": "blocked_by_guardrails"'; then
    echo "[$(date -u +%FT%TZ)] blocked by guardrails, stopping watcher" | tee -a "$LOG"
    exit 1
  fi

  sleep "$SLEEP_SEC"
done
