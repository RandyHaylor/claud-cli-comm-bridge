#!/usr/bin/env bash
# Usage: start.sh   -- starts the claude-bridge systemd user service
set -euo pipefail
systemctl --user start claude-bridge
echo "claude-bridge started"
