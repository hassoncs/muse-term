# muse-term

**Give your agent a terminal on your own Mac.**

Stock paired Muse can read and write files on your Mac, but it has no
shell: no `git clone`, no `bun install`, no `npm run dev`. muse-term
fixes that with two transports — pick per setup, both driven by your
agent once you're done:

| Transport | You get | Costs | Owner acts |
|---|---|---|---|
| **Tailscale + SSH** ⭐ recommended | Real TTY, live streaming, `scp`, Apple's own sshd, WireGuard encryption | A free Tailscale account | 4, all one-time: install Tailscale + sign in, turn on Remote Login, switch Muse's ssh permission from Deny to Ask, approve your agent's VM into your tailnet |
| **Reverse tunnel via serveo** (Transport 1b) ⭐ when the tailnet data plane fails | Real SSH, TTY, `scp` — the Mac dials *out*, your SSH rides back in | No account; forwarded port is public, ~256 KiB/s cap, port rotates per reconnect | 2: Remote Login on + one launchd bootstrap (your agent can place the plist with its file access; it loads at your next login, or immediately via one paste) |
| Reverse tunnel via pinggy | Same idea as serveo, connected faster in our tests | Free sessions expire after ~60 minutes | Same as serveo |
| **File-drop daemon** (in this repo) | Shell via job files — streaming progress + PTY sessions included | No accounts, no network at all | 1: paste one install line |
| Hosted relay / ngrok-style tunnel | — | *Not shipped as the answer:* ngrok works but needs your own account + authtoken on the Mac; a hosted relay adds a third party to trust | — |

Plus a **simulated floor** in [`sim/`](sim/): `m5sh`, an ssh-*like*
persistent shell (tmux-backed, over a file/relay exec channel) that
shows how low the floor goes when no real SSH path exists at all, and
`m5-ssh`, the port-lookup wrapper for the serveo tunnel. Reference
implementations from the fleet that proved all of the above.

**Point your agent at [`AGENT.md`](AGENT.md)** — it's a guided setup
written for the agent, with a verification gate per phase and a failure
ladder that falls back to file-drop so you're never left with nothing.

## How the flagship works (Tailscale + SSH)

Your agent's VM joins *your* private Tailscale network (you approve a
join link — outbound only, nothing hosted). Your agent then writes its
own SSH public key into `~/.ssh/authorized_keys` on your Mac **using the
file access it already has**, and from then on it's just:

```sh
ssh mac-ts 'cd ~/Workspaces && git clone … && bun install && bun run dev'
```

No daemon to write, nothing custom running on your Mac — the server is
Apple's sshd, the network is WireGuard. The full walk-through, proxy
config, and proofs (`hostname`, plus a `tty` check) are in `AGENT.md`.

## How file-drop works (fallback)

```
  Your agent (paired, remote)                 Your Mac
 ┌──────────────────────────┐   files.write  ┌────────────────────────┐
 │ writes job-<id>.json ────┼───────────────▶│ ~/muse-term/bridge/    │
 │ {id, token, command}     │                │  runner.py (launchd)   │
 │ watches status-<id>.json │                │  runs /bin/zsh -lc …   │
 │ + <id>.out.partial       │◀── streaming ──│  partial output, live  │
 │ reads result-<id>.json ◀─┼─── files.read ─│ result-<id>.json       │
 └──────────────────────────┘                └────────────────────────┘
```

The daemon (~300 lines of Python, stdlib only, **no network**) also
supports **PTY sessions**: interactive shells and prompts under a real
pseudo-terminal, typed into via files. See `AGENT.md` for the protocol.

### The one human act (file-drop only)

Your agent **cannot install this itself** — installing takes a shell,
which is exactly what it doesn't have. You do one thing, once, in
Terminal on your Mac:

```sh
git clone https://github.com/YOUR-ORG/muse-term.git && cd muse-term && ./mac/install.sh
```

(Repo URL is a placeholder until the project is published under its
final name/home.) The installer prints one line to give back to your
agent; from then on the agent drives everything. Missing `python3`?
The installer tells you to run `xcode-select --install` first.

## Why file-drop?

Because for a stranger's setup it's the transport that *cannot fail to
connect*:

- **No inbound network/NAT problem.** Your agent's VM has no route to
  your Mac — it's behind your home NAT, on a network the VM isn't part
  of. That's precisely the gap Tailscale fills for the flagship; if you
  don't want an account, files are the channel that already reaches
  the Mac: the pairing itself.
- **No hosted server to trust.** Nothing of yours transits or rests on
  a third-party relay. Job files live on your Mac, full stop.
- **Filesystem semantics do the heavy lifting.** Atomic rename
  (write `.tmp`, rename to `.json`) means no half-written jobs, ever;
  a folder listing is a queue; a result file existing *is* the
  completion signal.
- **The tradeoff is latency:** ~1–3s per round trip (0.5s daemon poll +
  your agent's read poll) instead of milliseconds. For builds, clones
  and installs — the jobs this exists for — that's invisible, and
  streaming partial output means long jobs are watchable, not opaque.
- **History, honestly:** an earlier version of this idea (Oct 2026,
  built for one specific fleet) was never proven live — but what failed
  was the *bootstrap*: the daemon was placed on the Mac and never
  installed, because installing needed the shell it was meant to
  provide. The transport itself was never the problem. muse-term's
  answer is to say so up front: one human paste, then it runs.

## Pluggable transport

File-drop is the zero-setup **default**, not the architecture. The
job/result/status protocol is transport-agnostic: a job is JSON, a
result is JSON, status and partial output are files today and messages
tomorrow. The Mac-dials-*out* idea has since shipped in its simplest
form — not a websocket daemon but a plain reverse SSH tunnel
(Transport 1b, serveo/pinggy): outbound-only, no account, and the far
end is the owner's real sshd. A websocket relay transport remains a
documented option for lower latency, deliberately not built: SSH,
the reverse tunnel, and file-drop already cover the full-power,
dead-network, and zero-setup cases.

## Security model — read this

Either transport ends at the same place: **commands run as you**, with
your full user permissions. Install muse-term only if you want your
agent to have that.

- **SSH:** keys, not passwords. Your agent's key sits in
  `~/.ssh/authorized_keys` alongside any keys you already trust;
  removing that one line revokes it instantly. Traffic is encrypted
  end-to-end by WireGuard + SSH; Tailscale sees no command content.
- **Reverse tunnel (1b):** while the tunnel is up, the Mac's sshd
  login prompt is reachable from the public internet at the tunnel
  host's assigned port. Key auth is the protection (same
  `authorized_keys`); the random port is not a secret. Uninstall the
  tunnel when it isn't wanted.
- **File-drop:** the only trigger is a job file in
  `~/muse-term/bridge/` carrying the token from `~/muse-term/token`
  (mode `0600`, generated at install). Wrong token = never runs. There
  is **no network listener**. Anything that can already write files as
  you could already run code as you — file-drop adds no remote surface.
- **Never put secrets in commands.** On file-drop, job files persist
  (`bridge/done/`); over SSH, commands land in shell history. Treat
  both like history, because they are.
- **Undo:** SSH — remove the pubkey line / turn Remote Login off.
  File-drop — `./mac/uninstall.sh` removes the daemon, launchd entry,
  token, everything. Token rotation: delete the token file, re-run
  the installer.

## Requirements

- macOS. Flagship: Tailscale (free) + Remote Login (built in).
  File-drop: `python3` from Xcode Command Line Tools + `/bin/zsh` (stock).
- An agent with file access to the Mac and a shell on its own machine —
  for Muse, the standard paired Mac app with file access granted.

## Files

| Path | What |
|---|---|
| `AGENT.md` | The guided setup, written **for your agent**. Start here. |
| `agent/SKILL.md` | Short-form protocol for skill-based agents. |
| `mac/runner.py` | File-drop daemon: streaming, live status, PTY sessions. Stdlib only. |
| `mac/install.sh` / `mac/uninstall.sh` | Idempotent install/remove; launchd label `io.museterm.runner`, home `~/muse-term/`. |
| `mac/revtunnel.plist` + `revtunnel-install.sh` / `revtunnel-uninstall.sh` | Transport 1b: launchd reverse SSH tunnel via serveo, label `io.museterm.revtunnel`, log `/tmp/revtunnel.log`. |
| `sim/m5-ssh` / `sim/m5sh` | Simulated floor: serveo port-lookup SSH wrapper, and a tmux-backed ssh-like shell over an exec channel. |
| `client/client.py` | Optional tiny client for an agent running *on* the Mac. |
| `tests/test_local.py` | Local simulation incl. streaming + PTY tests (macOS/Linux). |

## FAQ

**Why is SSH the flagship if file-drop needs less setup?** Because once
it's up it's not a workaround — it's a real terminal: TTY, streaming,
`scp`, and forty years of tooling, with Apple's sshd as the only server.
File-drop exists for when you want zero accounts, or for the day SSH
setup hits a wall.

**Is this affiliated with Meta / Muse?** No. A community tool using
your agent's normal, granted access — nothing undocumented, no bypass.

## License

MIT — see `LICENSE`.
