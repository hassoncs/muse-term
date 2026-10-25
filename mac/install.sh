#!/bin/sh
# muse-term installer (macOS). Idempotent. The ONLY step a human must run.
# Overrides for testing: MUSETERM_HOME, MUSETERM_LABEL
set -eu
LABEL="${MUSETERM_LABEL:-io.museterm.runner}"
DEST="${MUSETERM_HOME:-$HOME/muse-term}"
SRC="$(cd "$(dirname "$0")" && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_NOW="$(id -u)"

[ "$(uname)" = "Darwin" ] || { echo "muse-term: macOS only."; exit 1; }
if ! /usr/bin/python3 --version >/dev/null 2>&1; then
  echo "muse-term: python3 not found. Run:  xcode-select --install"
  echo "Then click Install, wait for it to finish, and run this again."
  exit 1
fi
[ -x /bin/zsh ] || { echo "muse-term: /bin/zsh missing (unexpected)."; exit 1; }

mkdir -p "$DEST/bridge/done" "$HOME/Library/LaunchAgents"
cp "$SRC/runner.py" "$DEST/runner.py"
chmod +x "$DEST/runner.py"

if [ ! -s "$DEST/token" ]; then
  ( umask 077; /usr/bin/python3 -c \
    'import secrets,sys; sys.stdout.write(secrets.token_hex(32))' \
    > "$DEST/token" )
  echo "muse-term: generated new token at $DEST/token"
fi
chmod 600 "$DEST/token"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/python3</string>
    <string>$DEST/runner.py</string>
    <string>--home</string><string>$DEST</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$DEST/launchd.log</string>
  <key>StandardErrorPath</key><string>$DEST/launchd.log</string>
</dict></plist>
EOF

launchctl bootout "gui/$UID_NOW/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_NOW" "$PLIST"
launchctl kickstart -k "gui/$UID_NOW/$LABEL" 2>/dev/null || true

echo ""
echo "muse-term: installed and running (label $LABEL, home $DEST)"
echo "Give your Muse this line:"
echo "  muse-term is installed. Read the token at $DEST/token and follow AGENT.md in the muse-term repo to verify with a hostname job."
