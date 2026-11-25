#!/usr/bin/env bash
# Usage: install.sh [TARGET_FOLDER]   -- symlinks these helper scripts into TARGET_FOLDER (default ~/claude-cli-comms-bridge-scripts)
set -euo pipefail
target_folder=${1:-$HOME/claude-cli-comms-bridge-scripts}
scripts_folder=$(dirname "$(readlink -f "$0")")
mkdir -p "$target_folder"
for script_path in "$scripts_folder"/*.sh; do
  [ "$(basename "$script_path")" = install.sh ] && continue
  chmod +x "$script_path"
  ln -sf "$script_path" "$target_folder/"
  echo "linked $(basename "$script_path") -> $target_folder"
done
