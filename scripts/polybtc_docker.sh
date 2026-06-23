#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE="docker compose -f $ROOT/docker-compose.yml"

case "${1:-}" in
  up)
    $COMPOSE up -d
    ;;
  down)
    $COMPOSE down
    ;;
  status)
    $COMPOSE ps
    ;;
  run)
    shift
    $COMPOSE run --rm polybtc "$@"
    ;;
  *)
    echo "Usage: $0 {up|down|status|run <cmd...>}"
    exit 2
    ;;
esac
