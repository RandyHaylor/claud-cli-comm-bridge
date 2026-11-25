#!/usr/bin/env bash
# Usage: keys.sh TO TEXT...   -- types TEXT and Enter into bridge-launched session TO (name or short id)
set -euo pipefail
if [ $# -lt 2 ]; then echo "Usage: $0 TO TEXT..." >&2; exit 1; fi
target_session=$1
shift
bridge_local_port=$(cat "$HOME/.config/claude-bridge/local_port" 2>/dev/null || echo 8788)
curl -sS -G "http://127.0.0.1:${bridge_local_port}/keys" --data-urlencode "to=$target_session" --data-urlencode "text=$*"
echo
