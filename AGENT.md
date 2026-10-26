# muse-term — instructions for the AI agent reading this

You are an agent (e.g. a paired Muse) whose human owns a Mac. You can
read/write files on that Mac (`files.*`), and you have a shell on your
**own** computer (a VM) — but stock, you have **no shell on the Mac**.
This package fixes that, two ways:

- **Flagship: Tailscale + SSH.** Real TTY, streaming, `scp`. ~4 owner acts.
- **Transport 1b: reverse SSH tunnel via serveo.** Same real SSH, but
  the Mac dials *out* — use it when the Tailscale route's data plane is
  dead (Phase C banner gate fails). No account, no Tailscale.
- **Fallback: file-drop daemon.** Zero accounts, one paste; poll latency,
  streaming + emulated PTY. If SSH setup fails at any gate, land here so
  the owner is never left with nothing.

Walk the phases **in order, one owner act at a time**, and pass each
verification gate before continuing. Never batch owner acts.

---

## Phase A — owner acts on the Mac (you guide, they click)

**A1. Tailscale on the Mac.** Ask the owner to install the Tailscale app
on their Mac (tailscale.com/download or the Mac App Store), open it, and
sign in — creating a free account if they don't have one. Their Mac now
has a private *tailnet* address.
*Gate: none yet — you'll confirm the Mac from your side in Phase B.*

**A2. Remote Login ON.** Ask the owner to open
**System Settings → General → Sharing → Remote Login** and turn it **ON**
(allowing their own user). This starts Apple's built-in SSH server.
*Gate: can't be verified until the Phase C proof — a refusal there sends
you to the Failure ladder (check Muse's own ssh permission first).*

## Phase B-pre — your own outbound-SSH permission (check before the proof)

If an `ssh` attempt is refused with a banner like *"Outbound SSH is
turned off for this assistant. To allow it, ask the user to open Muse
settings -> Permissions -> Direct network protocols and switch ssh from
Deny to Ask"* — **STOP. This is a Muse app permission, not a Mac
problem.** Nothing on the Mac side is wrong and no Mac-side fix exists.
Ask the owner to open **Muse Settings → Permissions → Direct network
protocols** and switch **ssh** from **Deny** to **Ask** (or Allow),
then retry. **This is owner act #3** — count it in the human-acts list.
Expect it to surface at the Phase C proof; check for it there first
before diagnosing the Mac (see Failure ladder, item 1).

## Phase B — join your VM to the owner's tailnet (you do this)

Your computer has a built-in Tailscale client. From your own shell:

1. Run `/opt/hatch/bin/tailscale up`. It prints an approval **link**.
2. Show the link to the owner; only they can approve your VM into their
   tailnet. Wait — do not retry-loop; if approval was given later, run
   `up` again to pick it up.
3. Run `/opt/hatch/bin/tailscale status`. Find the owner's Mac in the
   device list and note **one** address for it — its `100.x` tailnet IP
   or its MagicDNS name. Keep using that exact form everywhere: each
   address form needs its own first-connection approval.

*Gate: `status` shows your VM joined AND the Mac listed. If the Mac is
absent, A1 isn't finished — go back, don't improvise.*

## Phase C — SSH keys via files, then prove it (you do this)

The chicken-and-egg problem (no shell on the Mac) is solved by your file
access: you write your public key onto the Mac directly.

1. **Keypair on your VM:** if `~/.ssh/id_ed25519.pub` doesn't exist on
   your own computer, generate it: `ssh-keygen -t ed25519 -N ''`.
   The private key never leaves your VM.
2. **Authorize it on the Mac:** `files.read` the Mac's
   `~/.ssh/authorized_keys` (if it doesn't exist, `files.mkdir` `~/.ssh`
   first and treat the file as empty). **Preserve every existing line.**
   If your pubkey line isn't there, append it and `files.write` the
   whole file back.
   *Permissions matter:* sshd's StrictModes refuses keys when home,
   `~/.ssh`, or `authorized_keys` are writable by anyone but the owner.
   Files created with default permissions normally pass. If the proof
   below fails with a modes error, the owner's one-line fix is in the
   Failure ladder.
3. **SSH config on your VM:** discover your egress proxy — take the host
   from your `HTTPS_PROXY` environment variable; the Tailscale route is
   the same proxy on **port 3130** (HTTP CONNECT). Write a stanza:
   ```
   Host mac-ts
       HostName <the Mac address you chose in Phase B>
       User <owner's Mac username>
       IdentityFile ~/.ssh/id_ed25519
       ProxyCommand socat - PROXY:<proxy-host>:%h:%p,proxyport=3130
   ```
   Check `which socat` on your VM; that's the known-working CONNECT
   client for this pattern.
4. **Prove it** (first connection to that address may pause for the
   owner's approval in your app — wait for it, don't treat it as failure):
   ```sh
   ssh mac-ts 'hostname; whoami'        # must print the Mac's name + owner
   ssh -tt mac-ts 'tty'                 # must print /dev/ttysNNN, not "not a tty"
   ```

*Gate: both succeed. Now tell the owner plainly: you have a real shell
on their Mac. Otherwise: Failure ladder.*

## Transport 1b — reverse SSH tunnel via serveo (use when the Tailscale banner gate fails)

**When:** your Phase C banner fetch through the port-3130 proxy closes
with no bytes (in our fleet's case: ~8s, zero bytes back, for *every*
tailnet peer). That is the agent-VM platform's Tailscale data plane
being dead — not a Mac fault and not fixable from either machine.
Don't keep retrying it. Reverse direction instead: **the Mac dials
out** to a public tunnel service and your SSH rides back in through
that outbound connection. (Proven end-to-end 2026-10-25 on the fleet's
own Mac, after the Tailscale route failed exactly this way.)

### Mac side — a launchd tunnel agent

The Mac runs one outbound command, kept alive by launchd
(`mac/revtunnel.plist` in this repo, label `io.museterm.revtunnel`):

```sh
/usr/bin/ssh -o ControlMaster=no -o ControlPath=none \
  -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 \
  -N -R 0:localhost:22 serveo.net
```

It forwards a serveo-assigned public port back to the Mac's own sshd
(so Phase A2 — Remote Login ON — is still required). Output goes to
`/tmp/revtunnel.log`, which prints lines like
`Allocated port 28420 for remote forward to localhost:22`.

**Getting it started when you only have file commands — the one
wrinkle, stated plainly:** you can *place* the tunnel but not *launch*
it. `files.write` the plist to
`~/Library/LaunchAgents/io.museterm.revtunnel.plist` on the Mac and it
loads automatically at the owner's **next login** (RunAtLoad). For an
immediate start you need one bootstrap: if the file-drop daemon (below)
is already installed, run
`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/io.museterm.revtunnel.plist`
as a job; otherwise the owner runs `mac/revtunnel-install.sh` once from
a clone (a Terminal paste, like the file-drop install). Either way it
is a one-time bootstrap — after that, launchd keeps the tunnel up with
zero further acts.

### Your side — connect

Same keypair and `authorized_keys` line as Phase C; nothing new to set
up on the Mac's sshd.

1. **Read the current port — every time.** The port rotates (below).
   `files.read` `/tmp/revtunnel.log` on the Mac and take the **last**
   `Allocated port NNNN` line.
2. Connect (note: the proxy here is your normal **web** proxy,
   port **3128** — the public internet route, *not* 3130):
   ```sh
   ssh -p <port> -i ~/.ssh/id_ed25519 \
     -o 'ProxyCommand=socat - PROXY:<web-proxy-host>:%h:%p,proxyport=3128' \
     <owner>@serveousercontent.com 'hostname; whoami'
   ```
   `<web-proxy-host>` = host from your `HTTPS_PROXY`, as in Phase C.
   `scp` works the same way (`scp -P <port>` + same ProxyCommand).
   The `sim/m5-ssh` wrapper in this repo automates the port lookup for
   the fleet's own setup; copy the pattern.

*Gate: same proof as Phase C — the Mac's real hostname + owner
username. Then Phase D applies, adding `-p <port>` and the
ProxyCommand to each command.*

### Caveats (all measured on the anonymous tier, 2026-10-25)

- **Port rotates on every reconnect.** Never cache it; re-read the log.
- **One forward per source** — one outbound tunnel connection per Mac.
- **Sessions expire:** ~10-minute expiry plus a ~2-minute idle close.
  launchd `KeepAlive` respawns the tunnel (with a *new* port), which
  masks the expiry — but a long SSH session can still drop mid-work;
  reconnect with the fresh port.
- **Throughput cap ~256 KiB/s.** Fine for shells and source trees;
  bulk copies will crawl — prefer the Tailscale route for those when
  it works.
- **PTY — proven, with a key caveat.** The serveo gateway itself
  allocates a TTY fine: `ssh -tt` with an ordinary key returned a real
  `/dev/ttysNNN` (tested 2026-10-25). **But** if your pubkey's line in
  `authorized_keys` is prefixed `restrict,…` (which includes
  `no-pty`), `ssh -tt` fails with *"PTY allocation request failed on
  channel 0"* — the key line, not serveo. Fixes: remove the `restrict`
  prefix from your key's line (an owner-visible change to their
  `authorized_keys` — do it openly), or work around it per-command with
  `script -q /dev/null <cmd>`, which allocates a PTY on the Mac side
  without an SSH PTY.
- **The forwarded port is public.** Anyone on the internet can reach
  the Mac's sshd login prompt at `serveousercontent.com:<port>` while
  the tunnel is up. Your protection is SSH key auth itself (the same
  `authorized_keys` from Phase C) — the random port is obscurity, not
  security. Remove the tunnel with `mac/revtunnel-uninstall.sh` when
  it's not wanted.
- **Alternatives, one line each:** pinggy (`ssh -R0:localhost:22
  tcp@a.pinggy.io`) connected faster in our tests but free sessions
  expire after ~60 minutes; localhost.run's free tier does not offer
  raw TCP/SSH forwarding (not viable); ngrok (`ngrok tcp 22`) works
  but needs the owner's own ngrok account and authtoken on the Mac.

---

## Phase D — daily use: plain SSH

Everything is ordinary `ssh` / `scp` from your VM. Examples:

```sh
ssh mac-ts 'cd ~/Workspaces && git clone https://github.com/imsvidskiy/dawnfolk.git'
ssh mac-ts 'cd ~/Workspaces/dawnfolk && bun install'
ssh mac-ts 'cd ~/Workspaces/dawnfolk && nohup bun run dev > /tmp/dev.log 2>&1 &'
ssh mac-ts 'curl -s -o /dev/null -w "%{http_code}" http://localhost:5173'   # expect 200
scp mac-ts:~/Workspaces/dawnfolk/package.json ./   # files both ways
```

Long or interactive work: `ssh -tt` gives a real terminal. Background
servers with `nohup … &` and check their logs — don't hold an SSH
session open waiting on a dev server.

---

## Failure ladder — diagnose in this order, then fall back

1. **`ssh` refuses with "Outbound SSH is turned off for this
   assistant"** — especially when the banner fetch through the proxy
   succeeded but `ssh` itself refuses → this is Muse's own permission
   gate, not the Mac. Owner act #3: Muse Settings → Permissions →
   Direct network protocols → **ssh**: Deny → Ask (or Allow). Retry.
   Check this **first** whenever the Mac-side checks pass.
2. **Proxy/connect timeout** → your VM's tailnet join still pending?
   `/opt/hatch/bin/tailscale status`; re-show the approval link (Phase B).
   If the join is complete but the banner fetch through the proxy
   still closes empty (~8s, every peer), the data plane itself is
   dead — go to **Transport 1b** (reverse tunnel via serveo) instead
   of retrying.
3. **Connection reaches the Mac but port 22 refuses/closes** → Remote
   Login is off. Back to Phase A2.
4. **`Permission denied (publickey)`** → check `authorized_keys` content
   via `files.read` (your exact pubkey line present? existing lines
   intact?). If content is right, it's modes — ask the owner to run one
   Terminal line: `chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys`,
   then retry.
5. **Host-key / changed-key warnings** → stop; show the owner, don't
   delete `known_hosts` entries silently.
6. **Still stuck → Transport 1b if you haven't tried it, then the
   file-drop fallback below.** The owner is never left with nothing,
   and file-drop needs no network at all. SSH can be revisited later;
   all three can coexist.

---

## Fallback — file-drop daemon (`mac/runner.py`)

Zero accounts, no network. Poll latency ~1–3s is the price.

### The one human act (you cannot do this step)

Installing takes a shell — the thing you're missing. Ask the owner to
paste **one line** in Terminal on the Mac:

```sh
git clone https://github.com/YOUR-ORG/muse-term.git && cd muse-term && ./mac/install.sh
```

(URL is a placeholder until the project is published; use the repo URL
you were pointed at.) The installer prints a confirmation line for the
owner to paste back to you. If it reports `python3 not found`, the owner
runs `xcode-select --install`, clicks Install, then re-runs the line.

### Verify

1. `files.read` `~/muse-term/token` (expand `~` to the owner's home).
   Keep it in-session only; never print it.
2. Drop a test job (protocol below): command `hostname; whoami; pwd`.
3. Poll the result file every ~2s, up to 30s. Success = `ok:true`,
   `exit_code:0`, stdout = the Mac's hostname + owner's username.

### Protocol

`BRIDGE = <home>/muse-term/bridge`. Ids: `[A-Za-z0-9_-]`, max 64 chars.

**One-shot job** — `files.write` `BRIDGE/job-<id>.tmp`, then
`files.rename` it to `job-<id>.json` (atomic; never write `.json`
directly if you can rename):
```json
{"id":"<id>","token":"<token>","command":"<zsh command>","cwd":"<optional abs path>","timeout":120}
```
`timeout` default 120, max 600. Jobs run sequentially, filename order.

**Watch it live** — don't wait blind for long commands:
- `BRIDGE/status-<id>.json`: `{"state":"queued|running|done","pid",
  "started_at","heartbeat","exit_code"}` — refreshed ≥2×/s while running.
- `BRIDGE/<id>.out.partial` / `<id>.err.partial`: stdout/stderr **so
  far**, flushed as the command produces it. Read them mid-run to watch
  a build. They are deleted when the final result is written.

**Result** — `BRIDGE/result-<id>.json`:
```json
{"id":"<id>","ok":true,"stdout":"…","stderr":"…","exit_code":0,"duration_ms":123,"timed_out":false}
```
`ok:true` means the command *ran*; its own failure is `exit_code`
(exit 3 → `ok:true, exit_code:3`). `ok:false` = the job itself failed
(`error`: bad token, timeout with `timed_out:true`, missing cwd).
Streams are capped at 256 KB each — for more, redirect to a file on the
Mac inside the command and `files.read` that file.

**PTY session job** — interactive programs, prompts, REPLs:
```json
{"id":"<id>","token":"<token>","type":"session","timeout":600}
```
Add `"command":"…"` to run one command under a real pseudo-terminal
instead of an interactive `zsh`. Then:
- Output (merged stdout+stderr, as a terminal shows it) streams to
  `BRIDGE/session-<id>.out` — poll it with `files.read`.
- You "type" by writing `BRIDGE/stdin-<id>-<seq>.txt` files
  (`seq` = 1, 2, 3…): raw text incl. `\n` for Return. Consumed in seq
  order, then deleted. One logical keystroke batch per file.
- Control: write `BRIDGE/control-<id>.json`:
  `{"action":"interrupt"}` (Ctrl-C), `{"action":"eof"}` (Ctrl-D),
  `{"action":"resize","rows":40,"cols":120}`, `{"action":"close"}` (kill).
- Session end (shell exits, `close`, or timeout) writes the usual
  `result-<id>.json` with the full session output in `stdout`.

**Cleanup & rules:** the daemon archives jobs to `BRIDGE/done/` itself;
delete consumed results with `files.trash`. **Never put secrets in
commands** — job files persist on disk; they are shell history in JSON.
Commands run as the owner in their login shell. Broken? Owner re-runs
`./mac/install.sh` (idempotent); token rotation = delete
`~/muse-term/token` + re-run install; `./mac/uninstall.sh` removes all.
