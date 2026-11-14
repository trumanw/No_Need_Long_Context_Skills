#!/usr/bin/env bash
# Copy the plugin into ~/.cursor/plugins/local/ for testing; Cursor skips symlinks
# that point outside that directory. Rerun after each edit, then Developer: Reload Window.
#   tools/plugin_local_install.sh            install or refresh
#   tools/plugin_local_install.sh --remove   uninstall
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
name="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["name"])' "$repo/.cursor-plugin/plugin.json")"
dest="${CURSOR_LOCAL_PLUGINS_DIR:-$HOME/.cursor/plugins/local}/$name"
rm -rf "$dest"
if [ "${1:-}" = "--remove" ]; then
  echo "removed $dest"
  exit 0
fi
mkdir -p "$dest"
cp -R "$repo/.cursor-plugin" "$repo/skills" "$repo/README.md" "$repo/LICENSE" "$dest/"
find "$dest" -name __pycache__ -type d -prune -exec rm -rf {} +
echo "installed $dest; run Developer: Reload Window, then check Customize"
