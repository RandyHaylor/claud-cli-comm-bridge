#!/usr/bin/env bash
# Usage: recent-slack.sh [CHANNEL_ID]   -- prints the Slack messages the bridge has stored (all channels if none given)
set -euo pipefail
bridge_local_port=$(cat "$HOME/.config/claude-bridge/local_port" 2>/dev/null || echo 8788)
curl -sS -G "http://127.0.0.1:${bridge_local_port}/slack/messages" --data-urlencode "channel=${1:-}" | python3 -m json.tool
