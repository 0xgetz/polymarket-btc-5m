#!/usr/bin/env bash
set -euo pipefail

PROFILE="${1:-conservative}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CTL="$SCRIPT_DIR/polybtc_ctl.sh"

if [[ "$PROFILE" != "conservative" && "$PROFILE" != "aggressive" ]]; then
  echo "Usage: $0 [conservative|aggressive]"
  exit 2
fi

exec "$CTL" start --profile "$PROFILE"
