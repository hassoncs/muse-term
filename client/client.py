#!/usr/bin/env python3
"""Tiny muse-term client for agents that run ON the Mac itself.
Paired (remote) Muse does not need this: it uses files.write/files.read
directly, exactly as AGENT.md describes -- this file is the same protocol.

Usage: python3 client.py [--home ~/muse-term] "hostname; whoami"
Prints the result JSON; process exit code mirrors the remote exit_code.
"""
import argparse, json, os, secrets, sys, time

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", default=os.path.expanduser("~/muse-term"))
    ap.add_argument("--cwd"); ap.add_argument("--timeout", type=int)
    ap.add_argument("--wait", type=int, default=130)
    ap.add_argument("command")
    a = ap.parse_args()
    home = os.path.expanduser(a.home)
    bridge = os.path.join(home, "bridge")
    with open(os.path.join(home, "token")) as f:
        token = f.read().strip()
    jid = secrets.token_hex(6)
    job = {"id": jid, "token": token, "command": a.command}
    if a.cwd: job["cwd"] = a.cwd
    if a.timeout: job["timeout"] = a.timeout
    tmp = os.path.join(bridge, f"job-{jid}.tmp")
    with open(tmp, "w") as f:
        json.dump(job, f)
    os.rename(tmp, os.path.join(bridge, f"job-{jid}.json"))  # atomic drop
    result = os.path.join(bridge, f"result-{jid}.json")
    deadline = time.time() + a.wait
    while time.time() < deadline:
        if os.path.exists(result):
            with open(result) as f:
                r = json.load(f)
            print(json.dumps(r, indent=2))
            return r["exit_code"] if r.get("exit_code") is not None else 1
        time.sleep(0.5)
    print(f"muse-term: no result for job {jid} after {a.wait}s",
          file=sys.stderr)
    return 2

if __name__ == "__main__":
    sys.exit(main())
