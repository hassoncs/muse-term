#!/bin/sh
# muse-term Transport 1b — install the serveo reverse-tunnel LaunchAgent.
# Idempotent. Requires Remote Login ON (System Settings → General →
# Sharing) so the tunnel has a local sshd to forward to.
set -eu
LABEL=io.museterm.revtunnel
SRC="$(cd "$(dirname "$0")" && pwd)/revtunnel.plist"
DST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$HOME/Library/LaunchAgents"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
cp "$SRC" "$DST"
launchctl bootstrap "gui/$(id -u)" "$DST"
sleep 3
PORT=$(grep 'Allocated port' /tmp/revtunnel.log 2>/dev/null | tail -1 \
  | sed -n 's/.*Allocated port \([0-9][0-9]*\).*/\1/p')
echo "revtunnel installed. Serveo port: ${PORT:-<not yet allocated — check /tmp/revtunnel.log>}"
echo "Tell your agent: the current port is the last 'Allocated port' line in /tmp/revtunnel.log on this Mac."
