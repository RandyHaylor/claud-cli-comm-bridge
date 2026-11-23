#!/usr/bin/env bash
# Creates ~/remote-sessions/<new chat id>/, opens a new terminal there and starts
# Claude Code with that session name.
# Usage: new_remote_session.sh [session-name]   (default name: remote-<chat id>)
set -euo pipefail

chat_id="$(date +%Y%m%d-%H%M%S)-$(head -c 3 /dev/urandom | od -An -tx1 | tr -d ' \n')"
session_name="${1:-remote-${chat_id}}"
session_directory="${HOME}/remote-sessions/${chat_id}"

mkdir -p "${session_directory}"
gnome-terminal --working-directory="${session_directory}" --title="${session_name}" \
  -- bash -lc 'claude --name "$1"; exec bash' _ "${session_name}"

echo "chat id: ${chat_id}"
echo "folder: ${session_directory}"
echo "session name: ${session_name}"
