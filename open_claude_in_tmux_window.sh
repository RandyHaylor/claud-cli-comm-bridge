#!/usr/bin/env bash
# Starts Claude Code inside a tmux session on the bridge's own tmux server, then opens a visible
# gnome-terminal window attached to it. Because the session lives in tmux, the bridge can later
# type into it (for example /compact) with tmux send-keys.
# Usage: open_claude_in_tmux_window.sh SESSION_NAME WORKING_DIRECTORY [extra claude arguments...]
set -euo pipefail

session_name="$1"
working_directory="$2"
shift 2

bridge_tmux_server="claude-bridge"
# tmux treats '.' and ':' in targets as window/pane separators, so the tmux session name avoids them.
tmux_session_name="bridge-${session_name//./_}"

# Unset every CLAUDE*/AI_AGENT variable except CLAUDE_CODE_TMPDIR before starting claude, so the
# session never inherits a parent Claude session's markers (which turn off transcript saving and
# stop it registering), even if the tmux server itself was started with them.
start_claude='for variable_name in $(compgen -e); do
  case "$variable_name" in CLAUDE_CODE_TMPDIR) ;; CLAUDE*|AI_AGENT) unset "$variable_name" ;; esac
done
claude "$@"; exec bash'

tmux_environment_arguments=()
if [[ -n "${CLAUDE_CODE_TMPDIR:-}" ]]; then
  tmux_environment_arguments=(-e "CLAUDE_CODE_TMPDIR=${CLAUDE_CODE_TMPDIR}")
fi

tmux -L "${bridge_tmux_server}" new-session -d -s "${tmux_session_name}" -c "${working_directory}" \
  "${tmux_environment_arguments[@]}" \
  bash -lc "${start_claude}" _ --name "${session_name}" "$@"

gnome-terminal --title="${session_name}" -- tmux -L "${bridge_tmux_server}" attach -t "=${tmux_session_name}"

echo "tmux session: ${tmux_session_name}"
