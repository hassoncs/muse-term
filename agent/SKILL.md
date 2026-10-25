---
name: muse-term
description: Get a shell on the owner's Mac. Flagship: Tailscale + SSH (agent-guided setup, real TTY). Fallback: muse-term file-drop daemon (job JSON into ~/muse-term/bridge, streaming status/partials, PTY sessions). Use when you need git/bun/npm or any shell command on a Mac you can only reach with file commands.
---

# muse-term (short form — full guided setup in ../AGENT.md)

## Flagship: Tailscale + SSH
1. Owner: installs/signs into Tailscale on the Mac; turns ON
   System Settings → General → Sharing → Remote Login. One act at a time.
2. You: `/opt/hatch/bin/tailscale up` → show owner the approval link →
   `tailscale status` → note the Mac's 100.x IP or MagicDNS name (pick one).
3. You: ensure VM keypair (`ssh-keygen -t ed25519 -N ''` if needed);
   `files.read` Mac `~/.ssh/authorized_keys`, preserve lines, append your
   pubkey, write back. Add ssh stanza with
   `ProxyCommand socat - PROXY:<HTTPS_PROXY host>:%h:%p,proxyport=3130`.
4. Gate: `ssh mac-ts 'hostname; whoami'` and `ssh -tt mac-ts 'tty'`
   must both succeed. Failure ladder (Muse's own outbound-SSH
   permission → join pending → Remote Login → authorized_keys/modes)
   is in ../AGENT.md.
   If `ssh` refuses with "Outbound SSH is turned off for this
   assistant" — a Muse app gate, not a Mac problem — STOP and ask the
   owner to switch **ssh** from Deny to Ask (or Allow) in Muse
   Settings → Permissions → Direct network protocols, then retry.
   This is owner act #3.
5. Daily use: plain `ssh`/`scp`; servers via `nohup … &` + curl checks.

## Fallback: file-drop (zero accounts)
Owner pastes once in Mac Terminal:
`git clone <this-repo-url> && cd muse-term && ./mac/install.sh`
You cannot install it — no shell yet. Then:
1. `files.read` `~/muse-term/token` once per session. Never print it.
2. Job: `files.write` `bridge/job-<id>.tmp` with
   `{"id","token","command","cwd"?,"timeout"?}`, rename to `job-<id>.json`.
3. Watch live: `bridge/status-<id>.json` (queued/running/done, pid,
   heartbeat) + `bridge/<id>.out.partial` / `.err.partial` streaming.
4. Result `bridge/result-<id>.json`:
   `{"ok","stdout","stderr","exit_code","duration_ms","timed_out"}`.
   `ok:true` + `exit_code:3` = ran, failed itself. `ok:false` = see `error`.
5. PTY session: job `{"type":"session","command"?,"timeout":600}` →
   output streams to `bridge/session-<id>.out`; type via
   `bridge/stdin-<id>-<seq>.txt` files; `bridge/control-<id>.json`
   `{"action":"interrupt|eof|close|resize"}`.
6. Never put secrets in commands — job files persist in `bridge/done/`.
