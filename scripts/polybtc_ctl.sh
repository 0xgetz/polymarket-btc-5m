#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNTIME_DIR="${POLYBTC_RUNTIME_DIR:-$SKILL_ROOT/runtime}"
WORKSPACE_ROOT="$(cd "$SKILL_ROOT/../.." && pwd)"
REPO_DEFAULT="$WORKSPACE_ROOT/pm-hl-conservative-plus-repo"
REPO="${POLYBTC_REPO:-$REPO_DEFAULT}"
RUNNER="${POLYBTC_RUNNER:-$SKILL_ROOT/scripts/test_polybtc_session_exit_sl.py}"
ENV_FILE="${POLYBTC_ENV_FILE:-$REPO/.env}"

resolve_python() {
  if [[ -n "${POLYBTC_PY:-}" && -x "${POLYBTC_PY}" ]]; then
    echo "$POLYBTC_PY"
    return
  fi
  if [[ -x "$REPO/.venv/bin/python" ]]; then
    echo "$REPO/.venv/bin/python"
    return
  fi
  if [[ -x "$SKILL_ROOT/.venv/bin/python" ]]; then
    echo "$SKILL_ROOT/.venv/bin/python"
    return
  fi
  command -v python3 || command -v python
}

VENV_PY="$(resolve_python)"

PIDFILE="$RUNTIME_DIR/polybtc.pid"
METAFILE="$RUNTIME_DIR/polybtc.meta.json"
LATEST_LINK="$RUNTIME_DIR/latest.log"
LOCKFILE="$RUNTIME_DIR/polybtc.lock"

mkdir -p "$RUNTIME_DIR"

usage() {
  cat <<'USAGE'
Usage:
  polybtc_ctl.sh start [--profile conservative|aggressive] [--live] [runner flags...]
  polybtc_ctl.sh status
  polybtc_ctl.sh stop
  polybtc_ctl.sh report [--limit N]
  polybtc_ctl.sh logs

Safety:
  - Default is DRY-RUN (no --execute). Pass --live to place real orders.
  - Auth/env from pm-hl-conservative-plus-repo/.env (or POLYBTC_ENV_FILE).
  - Runtime isolated under ./runtime (or POLYBTC_RUNTIME_DIR).
USAGE
}

is_running() {
  if [[ -f "$PIDFILE" ]]; then
    local pid
    pid="$(cat "$PIDFILE" 2>/dev/null || true)"
    [[ -n "$pid" ]] && ps -p "$pid" >/dev/null 2>&1
  else
    return 1
  fi
}

cmd_start() {
  local profile="conservative"
  local entry_timeout_min="35"
  local stake_usd=""
  local threshold=""
  local poll_sec="2"
  local close_retry_max="30"
  local close_retry_delay_sec="2"
  local live=0
  local extra=()

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --profile) profile="$2"; shift 2;;
      --entry-timeout-min) entry_timeout_min="$2"; shift 2;;
      --stake-usd) stake_usd="$2"; shift 2;;
      --threshold) threshold="$2"; shift 2;;
      --poll-sec) poll_sec="$2"; shift 2;;
      --close-retry-max) close_retry_max="$2"; shift 2;;
      --close-retry-delay-sec) close_retry_delay_sec="$2"; shift 2;;
      --live|--execute) live=1; shift;;
      --dry-run) live=0; shift;;
      *) extra+=("$1"); shift;;
    esac
  done

  if is_running; then
    echo "already_running pid=$(cat "$PIDFILE")"
    return 0
  fi

  if [[ -f "$LOCKFILE" ]]; then
    local lpid
    lpid="$(cat "$LOCKFILE" 2>/dev/null || true)"
    if [[ -n "$lpid" ]] && ps -p "$lpid" >/dev/null 2>&1; then
      echo "lock_held pid=$lpid"
      return 0
    fi
    rm -f "$LOCKFILE"
  fi

  local ts log
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  log="$RUNTIME_DIR/polybtc_${profile}_${ts}.log"

  local -a runner_cmd
  runner_cmd=(
    "$VENV_PY" "$RUNNER"
    "--profile" "$profile"
    "--entry-timeout-min" "$entry_timeout_min"
    "--poll-sec" "$poll_sec"
    "--close-retry-max" "$close_retry_max"
    "--close-retry-delay-sec" "$close_retry_delay_sec"
    "--runtime-dir" "$RUNTIME_DIR"
  )
  [[ -n "$stake_usd" ]] && runner_cmd+=("--stake-usd" "$stake_usd")
  [[ -n "$threshold" ]] && runner_cmd+=("--threshold" "$threshold")
  if [[ "$live" -eq 1 ]]; then
    runner_cmd+=("--execute")
    echo "WARNING: starting in LIVE mode (--execute). Real orders will be placed." >&2
  else
    echo "starting in DRY-RUN mode (pass --live to place real orders)"
  fi
  if [[ ${#extra[@]} -gt 0 ]]; then
    runner_cmd+=("${extra[@]}")
  fi

  (
    if [[ -f "$ENV_FILE" ]]; then
      set -a
      # shellcheck disable=SC1090
      source "$ENV_FILE"
      set +a
    fi
    cd "$REPO"
    nohup "${runner_cmd[@]}" >"$log" 2>&1 &
    echo $! >"$PIDFILE"
    cp "$PIDFILE" "$LOCKFILE"
  )

  ln -sfn "$log" "$LATEST_LINK"
  local pid
  pid="$(cat "$PIDFILE")"

  cat >"$METAFILE" <<JSON
{
  "startedAt": "$(date -u +%FT%TZ)",
  "pid": $pid,
  "profile": "$profile",
  "live": $live,
  "entryTimeoutMin": $entry_timeout_min,
  "pollSec": $poll_sec,
  "closeRetryMax": $close_retry_max,
  "closeRetryDelaySec": $close_retry_delay_sec,
  "log": "$log",
  "repo": "$REPO"
}
JSON

  sleep 1
  if ps -p "$pid" >/dev/null 2>&1; then
    echo "started pid=$pid live=$live log=$log"
  else
    echo "failed_to_start (check $log)"
    rm -f "$PIDFILE" "$LOCKFILE"
    exit 1
  fi
}

cmd_status() {
  if is_running; then
    local pid
    pid="$(cat "$PIDFILE")"
    echo "running pid=$pid"
    ps -p "$pid" -o pid=,etime=,command=
  else
    echo "stopped"
  fi
  if [[ -f "$METAFILE" ]]; then
    echo "meta=$METAFILE"
  fi
  if [[ -L "$LATEST_LINK" ]]; then
    echo "latest_log=$(readlink "$LATEST_LINK")"
  fi
}

cmd_stop() {
  if ! is_running; then
    echo "already_stopped"
    rm -f "$PIDFILE" "$LOCKFILE"
    return 0
  fi
  local pid
  pid="$(cat "$PIDFILE")"
  # Graceful first: allow runner to finish close path if it traps SIGTERM.
  kill -TERM "$pid" 2>/dev/null || true
  local i
  for i in 1 2 3 4 5 6 7 8 9 10; do
    if ! ps -p "$pid" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  if ps -p "$pid" >/dev/null 2>&1; then
    echo "warning: process still alive after SIGTERM; sending SIGKILL (open positions may remain)" >&2
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$PIDFILE" "$LOCKFILE"
  echo "stopped pid=$pid"
  echo "note: if a live position was open, verify/flatten manually on Polymarket"
}

cmd_report() {
  local limit="20"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --limit) limit="$2"; shift 2;;
      *) echo "Unknown arg: $1"; usage; exit 2;;
    esac
  done
  local py
  py="$(resolve_python)"
  "$py" "$SKILL_ROOT/scripts/polybtc_report.py" --runtime-dir "$RUNTIME_DIR" --limit "$limit"
}

cmd_logs() {
  if [[ -L "$LATEST_LINK" ]]; then
    tail -n 120 "$(readlink "$LATEST_LINK")"
  else
    echo "no_logs"
  fi
}

main() {
  local cmd="${1:-}"
  [[ -z "$cmd" ]] && { usage; exit 2; }
  shift || true
  case "$cmd" in
    start) cmd_start "$@" ;;
    status) cmd_status ;;
    stop) cmd_stop ;;
    report) cmd_report "$@" ;;
    logs) cmd_logs ;;
    *) usage; exit 2 ;;
  esac
}

main "$@"
