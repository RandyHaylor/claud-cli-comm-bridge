#!/usr/bin/env bash
# Usage: fork.sh FROM NEW_NAME   -- forks session FROM (name or short id) into a new session NEW_NAME
set -euo pipefail
if [ $# -ne 2 ]; then echo "Usage: $0 FROM NEW_NAME" >&2; exit 1; fi
bridge_local_port=$(cat "$HOME/.config/claude-bridge/local_port" 2>/dev/null || echo 8788)
curl -sS -G "http://127.0.0.1:${bridge_local_port}/fork" --data-urlencode "from=$1" --data-urlencode "name=$2"
echo
