#!/usr/bin/env bash
set -euo pipefail

PROFILE="${1:-conservative}"
MODE="${2:-}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CTL="$SCRIPT_DIR/polybtc_ctl.sh"

if [[ "$PROFILE" != "conservative" && "$PROFILE" != "aggressive" ]]; then
  echo "Usage: $0 [conservative|aggressive] [--live]"
  exit 2
fi

if [[ "$MODE" == "--live" || "$MODE" == "live" ]]; then
  exec "$CTL" start --profile "$PROFILE" --live
fi
exec "$CTL" start --profile "$PROFILE"
