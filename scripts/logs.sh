#!/usr/bin/env bash
# Usage: logs.sh   -- follows the claude-bridge service log (Ctrl+C to quit)
set -euo pipefail
journalctl --user -u claude-bridge -f
