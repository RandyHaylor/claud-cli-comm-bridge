#!/usr/bin/env bash
# Usage: subscribe.sh NAME   -- types /slack-subscribe into bridge-launched session NAME
set -euo pipefail
if [ $# -ne 1 ]; then echo "Usage: $0 NAME" >&2; exit 1; fi
bridge_local_port=$(cat "$HOME/.config/claude-bridge/local_port" 2>/dev/null || echo 8788)
curl -sS -G "http://127.0.0.1:${bridge_local_port}/keys" --data-urlencode "to=$1" --data-urlencode "text=/slack-subscribe"
echo
