#!/usr/bin/env bash
# Usage: sessions.sh   -- lists running Claude sessions as a name / short id / status / started table
set -euo pipefail
bridge_local_port=$(cat "$HOME/.config/claude-bridge/local_port" 2>/dev/null || echo 8788)
curl -sS "http://127.0.0.1:${bridge_local_port}/sessions" | python3 -c '
import json, sys
row_format = "{:<32} {:<10} {:<10} {}"
print(row_format.format("NAME", "SHORT_ID", "STATUS", "STARTED"))
for session in json.load(sys.stdin)["sessions"]:
    print(row_format.format(session["name"], session["short_id"], str(session["status"]), session["started"]))
'
