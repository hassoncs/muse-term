#!/bin/sh
# muse-term Transport 1b — remove the serveo reverse-tunnel LaunchAgent.
set -eu
LABEL=io.museterm.revtunnel
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
echo "revtunnel removed."
