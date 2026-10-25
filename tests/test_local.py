#!/usr/bin/env python3
"""Local simulation: run runner.py against a temp bridge, drop jobs with
client.py's protocol, assert results -- incl. live status/streaming and
a PTY session. Works on macOS and Linux (both ship /bin/zsh).
Run: python3 tests/test_local.py"""
import json, os, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(ROOT, "mac", "runner.py")
TOKEN = "test-token-123"
B = None  # bridge path, set in main

def drop(jid, job):
    tmp = os.path.join(B, f"job-{jid}.tmp")
    with open(tmp, "w") as f: json.dump(job, f)
    os.rename(tmp, os.path.join(B, f"job-{jid}.json"))

def read_json(name, wait=15):
    p = os.path.join(B, name)
    end = time.time() + wait
    while time.time() < end:
        if os.path.exists(p):
            try:
                with open(p) as f: return json.load(f)
            except json.JSONDecodeError:
                pass
        time.sleep(0.2)
    raise AssertionError(f"no {name}")

def wait_text(path, needle, wait=15):
    end = time.time() + wait
    while time.time() < end:
        if os.path.exists(path):
            with open(path, errors="replace") as f:
                if needle in f.read(): return True
        time.sleep(0.2)
    raise AssertionError(f"{needle!r} never appeared in {path}")

def main():
    global B
    home = tempfile.mkdtemp(prefix="museterm-test-")
    B = os.path.join(home, "bridge"); os.makedirs(B)
    with open(os.path.join(home, "token"), "w") as f: f.write(TOKEN)
    os.chmod(os.path.join(home, "token"), 0o600)
    proc = subprocess.Popen([sys.executable, RUNNER, "--home", home,
                             "--poll", "0.2"])
    try:
        drop("t1", {"id": "t1", "token": TOKEN,
                    "command": "echo hello-muse-term"})
        r = read_json("result-t1.json")
        assert r["ok"] and r["exit_code"] == 0 and \
            "hello-muse-term" in r["stdout"], r
        s = read_json("status-t1.json")
        assert s["state"] == "done" and s["exit_code"] == 0, s
        print("PASS echo + exit 0 + status done:", r["stdout"].strip())

        drop("t2", {"id": "t2", "token": TOKEN,
                    "command": "echo out; echo err >&2; exit 3"})
        r = read_json("result-t2.json")
        assert r["ok"] and r["exit_code"] == 3 and "err" in r["stderr"], r
        print("PASS exit-code propagation: exit_code=3, ok=true")

        drop("t3", {"id": "t3", "token": "wrong",
                    "command": "echo should-not-run"})
        r = read_json("result-t3.json")
        assert not r["ok"] and "token" in r["error"], r
        print("PASS bad-token rejection:", r["error"])

        drop("t4", {"id": "t4", "token": TOKEN,
                    "command": "sleep 5", "timeout": 1})
        r = read_json("result-t4.json")
        assert not r["ok"] and r["timed_out"], r
        print("PASS timeout: timed_out=true after ~1s")

        drop("t5", {"id": "t5", "token": TOKEN,
                    "command": "python3 -c \"print('x'*300000)\""})
        r = read_json("result-t5.json")
        assert len(r["stdout"]) <= 256 * 1024 + 100 and \
            "truncated" in r["stdout"], len(r["stdout"])
        print("PASS output cap: stdout len", len(r["stdout"]))

        # Streaming + live status: first line must be visible mid-run.
        drop("t6", {"id": "t6", "token": TOKEN,
                    "command": "echo EARLY-LINE; sleep 3; echo LATE-LINE"})
        s = read_json("status-t6.json")
        assert s["state"] == "running" and s["pid"], s
        wait_text(os.path.join(B, "t6.out.partial"), "EARLY-LINE", wait=5)
        assert not os.path.exists(os.path.join(B, "result-t6.json"))
        print("PASS streaming: EARLY-LINE in .out.partial while running,",
              "status pid", s["pid"])
        r = read_json("result-t6.json")
        assert "LATE-LINE" in r["stdout"], r
        print("PASS streaming job completed with both lines")

        # PTY session: interactive zsh, type via stdin files.
        drop("s1", {"id": "s1", "token": TOKEN, "type": "session",
                    "timeout": 30})
        read_json("status-s1.json")
        spool = os.path.join(B, "session-s1.out")
        with open(os.path.join(B, "stdin-s1-1.txt"), "w") as f:
            f.write("echo PTY_OK_$((6*7))\n")
        wait_text(spool, "PTY_OK_42")
        with open(os.path.join(B, "stdin-s1-2.txt"), "w") as f:
            f.write("tty\n")
        wait_text(spool, "/dev/", wait=10)
        with open(os.path.join(B, "stdin-s1-3.txt"), "w") as f:
            f.write("exit\n")
        r = read_json("result-s1.json")
        assert r["ok"] and r["exit_code"] == 0, r
        assert "PTY_OK_42" in r["stdout"], r["stdout"][-200:]
        print("PASS PTY session: typed echo ran, tty reported, clean exit")
    finally:
        proc.terminate(); proc.wait(timeout=5)
    print("ALL TESTS PASS")

if __name__ == "__main__":
    main()
