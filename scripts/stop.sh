#!/usr/bin/env bash
# Usage: stop.sh   -- stops the claude-bridge systemd user service
set -euo pipefail
systemctl --user stop claude-bridge
echo "claude-bridge stopped"
