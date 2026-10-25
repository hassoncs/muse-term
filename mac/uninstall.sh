#!/bin/sh
# muse-term uninstaller: stops the daemon and removes everything.
# Overrides (must match install): MUSETERM_HOME, MUSETERM_LABEL
set -eu
LABEL="${MUSETERM_LABEL:-io.museterm.runner}"
DEST="${MUSETERM_HOME:-$HOME/muse-term}"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$PLIST"
rm -rf "$DEST"
echo "muse-term: uninstalled (daemon stopped, $DEST removed)."
