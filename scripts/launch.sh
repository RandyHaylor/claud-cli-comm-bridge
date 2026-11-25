#!/usr/bin/env bash
# Usage: launch.sh NAME   -- starts a new bridge session named NAME in a visible terminal
set -euo pipefail
if [ $# -ne 1 ]; then echo "Usage: $0 NAME" >&2; exit 1; fi
bridge_local_port=$(cat "$HOME/.config/claude-bridge/local_port" 2>/dev/null || echo 8788)
curl -sS -G "http://127.0.0.1:${bridge_local_port}/launch" --data-urlencode "name=$1"
echo
