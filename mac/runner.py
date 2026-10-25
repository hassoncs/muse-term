#!/usr/bin/env python3
"""muse-term runner: file-drop shell execution for a paired Muse.

Polls <home>/bridge/ for job-<id>.json files, runs each command with
/bin/zsh -lc as the owning user, streams output to <id>.out.partial /
<id>.err.partial while it runs, keeps a live status-<id>.json, and
writes the final result-<id>.json. Stdlib only. No network.

Job:    {"id","token","command", "cwd"?, "timeout"?}         (one-shot)
        {"id","token","type":"session", "command"?, "timeout"?}  (PTY)
Result: {"id","ok","stdout","stderr","exit_code","duration_ms","timed_out"}
  A command exiting 3 ran fine: ok=true, exit_code=3. ok=false only
  when the job itself could not run (bad token/JSON, missing cwd, timeout).
Status: {"id","state":"queued|running|done","pid","started_at",
         "heartbeat","exit_code"} -- updated at least twice a second.
PTY session: command runs under a real pseudo-terminal. Output spool:
  session-<id>.out (merged). Agent sends input as stdin-<id>-<seq>.txt
  files (consumed in seq order); control-<id>.json with
  {"action":"interrupt"|"eof"|"close"|"resize","rows":N,"cols":N}.
"""
import argparse, fcntl, hmac, json, os, pty, re, select, struct
import subprocess, sys, termios, threading, time

MAX_OUTPUT = 256 * 1024
DEFAULT_TIMEOUT, MAX_TIMEOUT = 120, 600
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

def cap(data: bytes) -> str:
    if len(data) > MAX_OUTPUT:
        data = data[:MAX_OUTPUT] + b"\n[muse-term: output truncated]"
    return data.decode("utf-8", "replace")

def atomic_write(path: str, text: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.rename(tmp, path)

class Runner:
    def __init__(self, home: str, poll: float = 0.5):
        self.home, self.poll = home, poll
        self.bridge = os.path.join(home, "bridge")
        self.done = os.path.join(self.bridge, "done")
        self.attempts, self.sessions = {}, {}
        os.makedirs(self.done, exist_ok=True)
        with open(os.path.join(home, "token"), encoding="utf-8") as f:
            self.token = f.read().strip()
        if not self.token:
            sys.exit("muse-term: token file is empty")

    def log(self, msg: str) -> None:  # metadata only, never command/output
        try:
            with open(os.path.join(self.home, "runner.log"), "a") as f:
                f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}\n")
        except OSError:
            pass

    def status(self, jid, state, pid=None, started=None, code=None):
        s = {"id": jid, "state": state, "pid": pid, "started_at": started,
             "heartbeat": time.time(), "exit_code": code}
        atomic_write(os.path.join(self.bridge, f"status-{jid}.json"),
                     json.dumps(s, indent=2) + "\n")

    def result(self, jid, ok, stdout="", stderr="", code=None, ms=0,
               timed_out=False, error=None):
        r = {"id": jid, "ok": ok, "stdout": stdout, "stderr": stderr,
             "exit_code": code, "duration_ms": ms, "timed_out": timed_out}
        if error:
            r["error"] = error
        atomic_write(os.path.join(self.bridge, f"result-{jid}.json"),
                     json.dumps(r, indent=2) + "\n")

    def fail(self, jid, name, path, error, started):
        ms = int((time.time() - started) * 1000)
        self.result(jid, False, error=error, ms=ms)
        self.status(jid, "done", started=started)
        self.log(f"job={jid} rejected ms={ms}")
        self.archive(path, name)

    def archive(self, path, name):
        try:
            os.rename(path, os.path.join(self.done, name))
        except OSError:
            pass

    # ---- one-shot jobs, streamed -------------------------------------
    def run_oneshot(self, job, jid, name, path):
        started = time.time()
        ms = lambda: int((time.time() - started) * 1000)
        cwd = job.get("cwd") or os.path.expanduser("~")
        if not os.path.isdir(cwd):
            return self.fail(jid, name, path, f"cwd does not exist: {cwd}",
                             started)
        timeout = job_timeout(job)
        out_p = os.path.join(self.bridge, f"{jid}.out.partial")
        err_p = os.path.join(self.bridge, f"{jid}.err.partial")
        self.status(jid, "running", started=started)
        with open(out_p, "wb") as out_f, open(err_p, "wb") as err_f:
            p = subprocess.Popen(["/bin/zsh", "-lc", job["command"]],
                                 cwd=cwd, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
            self.status(jid, "running", pid=p.pid, started=started)
            bufs = {p.stdout: (bytearray(), out_f),
                    p.stderr: (bytearray(), err_f)}
            for s in bufs:
                os.set_blocking(s.fileno(), False)
            timed_out, last_beat = False, 0.0
            while True:
                if time.time() - started > timeout:
                    timed_out = True
                    p.kill()
                    break
                ready, _, _ = select.select(list(bufs), [], [], 0.2)
                for s in ready:
                    chunk = os.read(s.fileno(), 65536)
                    if chunk:
                        buf, fobj = bufs[s]
                        buf += chunk
                        fobj.write(chunk)
                        fobj.flush()
                if time.time() - last_beat >= 0.5:
                    last_beat = time.time()
                    self.status(jid, "running", pid=p.pid, started=started)
                if p.poll() is not None:
                    for s, (buf, fobj) in bufs.items():  # drain
                        try:
                            while (c := os.read(s.fileno(), 65536)):
                                buf += c; fobj.write(c)
                        except OSError:
                            pass
                    break
            p.wait()
        code = None if timed_out else p.returncode
        out = cap(bytes(bufs[p.stdout][0])); err = cap(bytes(bufs[p.stderr][0]))
        if timed_out:
            self.result(jid, False, out, err, None, ms(), timed_out=True,
                        error=f"timed out after {timeout}s")
        else:
            self.result(jid, True, out, err, code, ms())
        self.status(jid, "done", pid=p.pid, started=started, code=code)
        self.log(f"job={jid} exit={code} timeout={timed_out} ms={ms()}")
        for spool in (out_p, err_p):
            try:
                os.unlink(spool)
            except OSError:
                pass
        self.archive(path, name)

    # ---- PTY sessions -------------------------------------------------
    def start_session(self, job, jid, name, path):
        t = threading.Thread(target=self.run_session, args=(job, jid),
                             daemon=True)
        self.sessions[jid] = t
        t.start()
        self.archive(path, name)

    def run_session(self, job, jid):
        started = time.time()
        ms = lambda: int((time.time() - started) * 1000)
        timeout = job_timeout(job)
        spool_p = os.path.join(self.bridge, f"session-{jid}.out")
        master, slave = pty.openpty()
        set_winsize(slave, job.get("rows", 24), job.get("cols", 80))
        cmd = (["/bin/zsh", "-lc", job["command"]] if job.get("command")
               else ["/bin/zsh", "-i"])
        env = dict(os.environ, TERM="xterm-256color")
        p = subprocess.Popen(cmd, stdin=slave, stdout=slave, stderr=slave,
                             cwd=job.get("cwd") or os.path.expanduser("~"),
                             env=env, start_new_session=True)
        os.close(slave)
        os.set_blocking(master, False)
        self.status(jid, "running", pid=p.pid, started=started)
        buf, last_beat, timed_out = bytearray(), 0.0, False
        with open(spool_p, "wb") as spool:
            while True:
                if time.time() - started > timeout:
                    timed_out = True
                    p.kill()
                    break
                ready, _, _ = select.select([master], [], [], 0.2)
                if ready:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        chunk = b""
                    if not chunk and p.poll() is not None:
                        break
                    buf += chunk; spool.write(chunk); spool.flush()
                self.feed_input(jid, master)
                self.apply_control(jid, master, p)
                if time.time() - last_beat >= 0.5:
                    last_beat = time.time()
                    self.status(jid, "running", pid=p.pid, started=started)
                if p.poll() is not None:
                    try:  # final drain
                        while (c := os.read(master, 65536)):
                            buf += c; spool.write(c)
                    except OSError:
                        pass
                    break
        p.wait()
        code = None if timed_out else p.returncode
        self.result(jid, not timed_out, cap(bytes(buf)), "", code, ms(),
                    timed_out=timed_out,
                    error="session timed out" if timed_out else None)
        self.status(jid, "done", pid=p.pid, started=started, code=code)
        self.log(f"session={jid} exit={code} timeout={timed_out} ms={ms()}")
        try:
            os.close(master)
        except OSError:
            pass

    def feed_input(self, jid, master):
        pat = re.compile(rf"^stdin-{re.escape(jid)}-(\d+)\.txt$")
        try:
            names = sorted((n for n in os.listdir(self.bridge) if pat.match(n)),
                           key=lambda n: int(pat.match(n).group(1)))
        except OSError:
            return
        for n in names:
            fp = os.path.join(self.bridge, n)
            try:
                with open(fp, "rb") as f:
                    data = f.read()
                os.write(master, data)
                os.unlink(fp)
            except OSError:
                pass

    def apply_control(self, jid, master, p):
        fp = os.path.join(self.bridge, f"control-{jid}.json")
        if not os.path.exists(fp):
            return
        try:
            with open(fp) as f:
                ctl = json.load(f)
            os.unlink(fp)
        except (OSError, json.JSONDecodeError):
            return
        act = ctl.get("action")
        try:
            if act == "interrupt":
                os.write(master, b"\x03")
            elif act == "eof":
                os.write(master, b"\x04")
            elif act == "close":
                p.kill()
            elif act == "resize":
                set_winsize(master, ctl.get("rows", 24), ctl.get("cols", 80))
        except OSError:
            pass

    # ---- main loop ------------------------------------------------------
    def handle(self, path, name) -> bool:
        """False = file may be a partial write; retry next poll."""
        jid = name[len("job-"):-len(".json")]
        if not ID_RE.match(jid):
            self.archive(path, name)
            return True
        try:
            with open(path, encoding="utf-8") as f:
                job = json.load(f)
        except (OSError, json.JSONDecodeError):
            n = self.attempts.get(name, 0) + 1
            self.attempts[name] = n
            if n < 5:
                return False
            self.fail(jid, name, path, "job file is not valid JSON",
                      time.time())
            return True
        self.attempts.pop(name, None)
        started = time.time()
        self.status(jid, "queued", started=started)
        if not isinstance(job, dict) or str(job.get("id", jid)) != jid:
            self.fail(jid, name, path, "job id mismatch", started)
        elif not hmac.compare_digest(str(job.get("token", "")), self.token):
            self.fail(jid, name, path, "bad or missing token", started)
        elif job.get("type") == "session":
            self.start_session(job, jid, name, path)
        elif not isinstance(job.get("command"), str) \
                or not job["command"].strip():
            self.fail(jid, name, path, "missing command", started)
        else:
            self.run_oneshot(job, jid, name, path)
        return True

    def loop(self):
        self.log(f"runner started pid={os.getpid()} bridge={self.bridge}")
        while True:
            try:
                names = sorted(os.listdir(self.bridge))
            except OSError:
                names = []
            for name in names:
                if name.startswith("job-") and name.endswith(".json"):
                    self.handle(os.path.join(self.bridge, name), name)
            time.sleep(self.poll)

def job_timeout(job) -> int:
    try:
        return max(1, min(int(job.get("timeout", DEFAULT_TIMEOUT)),
                          MAX_TIMEOUT))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT

def set_winsize(fd, rows, cols):
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ,
                    struct.pack("HHHH", int(rows), int(cols), 0, 0))
    except (OSError, ValueError):
        pass

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="muse-term file-drop runner")
    ap.add_argument("--home", default=os.environ.get(
        "MUSETERM_HOME", os.path.expanduser("~/muse-term")))
    ap.add_argument("--poll", type=float, default=0.5)
    a = ap.parse_args()
    Runner(os.path.expanduser(a.home), a.poll).loop()
