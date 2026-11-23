#!/usr/bin/env bash
# Creates ~/remote-sessions/<new chat id>/ and starts Claude Code there with that session name,
# inside the bridge's tmux server, in a new visible terminal window.
# Usage: new_remote_session.sh [session-name]   (default name: remote-<chat id>)
set -euo pipefail

chat_id="$(date +%Y%m%d-%H%M%S)-$(head -c 3 /dev/urandom | od -An -tx1 | tr -d ' \n')"
session_name="${1:-remote-${chat_id}}"
session_directory="${HOME}/remote-sessions/${chat_id}"

mkdir -p "${session_directory}"
"$(dirname "$0")/open_claude_in_tmux_window.sh" "${session_name}" "${session_directory}"

echo "chat id: ${chat_id}"
echo "folder: ${session_directory}"
echo "session name: ${session_name}"
