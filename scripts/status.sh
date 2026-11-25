#!/usr/bin/env bash
# Usage: status.sh   -- shows the claude-bridge service status and the Tailscale Funnel status
set -euo pipefail
echo "== claude-bridge service =="
systemctl --user status claude-bridge --no-pager || true
echo
echo "== tailscale funnel =="
tailscale funnel status || true
