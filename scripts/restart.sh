#!/usr/bin/env bash
# Usage: restart.sh   -- restarts the claude-bridge systemd user service
set -euo pipefail
systemctl --user restart claude-bridge
echo "claude-bridge restarted"
