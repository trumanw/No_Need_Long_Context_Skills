#!/usr/bin/env bash
# Link this repo's skills into ~/.cursor/skills so edits take effect without copying.
#   tools/dev_install.sh            install (symlink)
#   tools/dev_install.sh --remove   remove the symlinks
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
dest="${CURSOR_SKILLS_DIR:-$HOME/.cursor/skills}"
mkdir -p "$dest"
for skill in "$repo"/no-need-long-context/skills/*/; do
  name="$(basename "$skill")"
  link="$dest/$name"
  if [ "${1:-}" = "--remove" ]; then
    [ -L "$link" ] && rm "$link" && echo "removed $link"
    continue
  fi
  if [ -e "$link" ] && [ ! -L "$link" ]; then
    echo "skip $link: exists and is not a symlink" >&2
    continue
  fi
  ln -sfn "${skill%/}" "$link"
  echo "linked $link -> ${skill%/}"
done
