"""Far transfers: send files laptop to laptop over the internet, powered by croc.

croc (https://github.com/schollz/croc, MIT licence) connects two computers with a shared code,
encrypts everything end to end, and resumes interrupted transfers. WinDrop runs it hidden and
reads its progress lines.
"""
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

WORDS = """acorn amber anchor apple arrow aspen autumn badge bamboo banjo basil beacon berry birch biscuit
blossom bonfire breeze brook bubble butter cabin cactus camel canyon carpet castle cedar cherry cider
cinnamon citrus clover cloud cobalt comet copper coral cotton cricket crystal daisy delta desert dolphin
dragon dune eagle echo ember emerald falcon feather fern fiddle field fig flame forest fossil fountain fox
galaxy garden garnet ginger glacier globe granite grape grove harbor hazel heron honey horizon ivory jade
jasmine jungle kettle kite koala lagoon lantern lava lemon lily lime linen lotus lunar magnet mango maple
marble meadow melon meteor mint mirror monsoon moss mountain nectar nebula nutmeg oak oasis ocean olive
onyx orbit orchid otter owl palm panda paper parrot peach pearl pebble pepper piano pine planet plum polar
pond poppy prairie puzzle quartz quill rabbit radar rain raven reef ribbon river robin rocket rose ruby
saffron sage salmon sapphire satin shadow shell silver sky slate snow solar sparrow spice spring spruce
star stone storm sugar summit sun swan tango thunder tiger timber topaz tulip tundra turtle valley velvet
violet volcano walnut willow window winter wolf yarrow zebra zephyr""".split()

PROGRESS = re.compile(r"(\d{1,3})%\s*\|[^|]*\|\s*\(([^)]*)\)")
RISKY = {".exe", ".msi", ".bat", ".cmd", ".scr", ".com", ".ps1", ".vbs", ".js", ".jar", ".lnk", ".pif", ".reg"}


def find_croc():
    names = ["croc.exe", "croc"]
    bases = []
    if hasattr(sys, "_MEIPASS"):
        bases.append(Path(sys._MEIPASS) / "croc")
    exe_dir = Path(sys.executable).resolve().parent
    bases += [exe_dir / "croc", exe_dir / "_internal" / "croc"]
    here = Path(__file__).resolve().parent
    bases += [here.parent / "vendor" / "croc", here]
    for b in bases:
        for n in names:
            if (b / n).is_file():
                return b / n
    found = shutil.which("croc")
    return Path(found) if found else None


def new_code():
    return f"{secrets.randbelow(9000) + 1000}-" + "-".join(secrets.choice(WORDS) for _ in range(3))


def clean_code(text):
    """Accept the code however it was typed: spaces, capitals, extra dashes."""
    code = re.sub(r"[\s_]+", "-", (text or "").strip().lower())
    code = re.sub(r"-{2,}", "-", code).strip("-")
    if len(code) < 6 or not re.fullmatch(r"[a-z0-9-]+", code):
        return None
    return code


def unique_path(folder, name):
    p = folder / name
    stem, suffix, i = p.stem, p.suffix, 1
    while p.exists():
        p = folder / f"{stem} ({i}){suffix}"
        i += 1
    return p


class FarJob:
    """One send or receive. Runs croc in a thread, retries with the same code until done or cancelled."""

    def __init__(self, kind, code, paths=None, out_dir=None, work_dir=None, relay=None, on_event=None):
        self.kind, self.code = kind, code
        self.paths = [Path(p) for p in (paths or [])]
        self.out_dir = Path(out_dir) if out_dir else None
        self.work_dir = Path(work_dir) if work_dir else None
        self.relay = relay
        self.on_event = on_event or (lambda *a: None)
        self.proc = None
        self.cancelled = False
        self.lock = threading.Lock()
        self.state = {"phase": "starting", "pct": 0, "speed": "", "name": "", "size": "", "note": "",
                      "saved": [], "risky": False, "attempt": 0}
        self.thread = threading.Thread(target=self._run, daemon=True)

    # ---------- public ----------
    def start(self):
        self.thread.start()
        return self

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    @property
    def finished(self):
        return self.state["phase"] in ("done", "cancelled", "failed")

    def cancel(self):
        self.cancelled = True
        self._kill()
        self._set(phase="cancelled", note="")

    # ---------- internals ----------
    def _set(self, **kw):
        with self.lock:
            self.state.update(kw)

    def _kill(self):
        p = self.proc
        if p and p.poll() is None:
            try:
                p.kill()
            except OSError:
                pass

    def _staging(self):
        return self.work_dir / re.sub(r"[^a-z0-9-]", "", self.code)

    def _command(self):
        exe = find_croc()
        if not exe:
            raise FileNotFoundError("croc")
        cmd = [str(exe)]
        if self.relay:
            cmd += ["--relay", self.relay]
        if self.kind == "send":
            cmd += ["--disable-clipboard", "--ignore-stdin", "send", "--no-local"] + [str(p) for p in self.paths]
        else:
            cmd += ["--yes", "--out", str(self._staging())]
        return cmd

    def _run(self):
        if self.kind == "receive":
            self._staging().mkdir(parents=True, exist_ok=True)
        while not self.cancelled:
            self._set(attempt=self.state["attempt"] + 1)
            try:
                rc = self._once()
            except FileNotFoundError:
                self._set(phase="failed", note="The transfer engine is missing from this copy of WinDrop.")
                self.on_event("far_failed", self.code, "engine missing")
                return
            if self.cancelled:
                return
            if rc == 0 and self.state["phase"] != "failed":
                if self.kind == "receive":
                    self._deliver()
                self._set(phase="done", pct=100, speed="", note="")
                self.on_event("far_done", self.kind, self.snapshot())
                return
            self._set(phase="retrying", speed="",
                      note="Connection lost. Reconnecting with the same code…" if getattr(self, "ever_connected", False)
                      else self.state["note"] or "Can't reach the other laptop right now. Trying again…")
            for _ in range(30):
                if self.cancelled:
                    return
                time.sleep(0.1)

    def _once(self):
        env = dict(os.environ, CROC_SECRET=self.code)
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self.proc = subprocess.Popen(self._command(), env=env, cwd=str(self.paths[0].parent) if self.paths else None,
                                     stdin=subprocess.PIPE if self.kind == "receive" else subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=flags)
        connected = False
        self._set(phase="connecting", note="Connecting…")

        def still_waiting():
            if not self.cancelled and self.proc.poll() is None and self.state["phase"] in ("connecting", "starting"):
                self._set(phase="waiting", note=("Waiting for the sender. Check the code, and that WinDrop is open "
                                                 "on the sending laptop.") if self.kind == "receive" else
                          "Waiting for the other laptop to enter the code…")
        timer = threading.Timer(12, still_waiting)
        timer.daemon = True
        timer.start()
        buf = b""
        out = self.proc.stdout
        while True:
            chunk = out.read1(4096) if hasattr(out, "read1") else out.read(4096)
            if not chunk:
                break
            buf += chunk
            parts = re.split(rb"[\r\n]", buf)
            buf = parts.pop()
            for raw in parts:
                line = raw.decode("utf-8", "replace").strip()
                if line:
                    connected = self._line(line) or connected
            # a prompt has no line ending yet: look at the unfinished text too
            tail = buf.decode("utf-8", "replace")
            if self.kind == "receive" and ("(y/N)" in tail or "(Y/n)" in tail):
                self._answer_yes()
                buf = b""
        timer.cancel()
        rc = self.proc.wait()
        if rc != 0 and not connected:
            self._set(note="Can't reach the other laptop right now. Trying again…")
        self.ever_connected = getattr(self, "ever_connected", False) or connected
        return rc

    def _answer_yes(self):
        try:
            self.proc.stdin.write(b"y\n")
            self.proc.stdin.flush()
        except OSError:
            pass

    def _line(self, line):
        """Read one line of croc output. Returns True once the other side is connected."""
        if line.startswith("Hashing"):
            m = re.search(r"(\d{1,3})%", line)
            if self.kind == "receive":
                self._set(phase="verifying", note="Verifying the received file…")
                return True
            self._set(phase="preparing", pct=int(m.group(1)) if m else 0, note="Getting the file ready…")
            return False
        if line.startswith("Checking"):
            self._set(phase="checking", note="Checking what was already received…")
            return True
        if line.startswith("connecting") or line.startswith("securing channel"):
            return False
        if line.startswith("Code is:"):
            self._set(phase="waiting", pct=0, note="Waiting for the other laptop to enter the code…")
            return False
        m = re.match(r"(Sending|Receiving) (?:'(.+)'|(\d+) files?) \(([^)]+)\)", line)
        if m:
            name = m.group(2) or f"{m.group(3)} files"
            self._set(name=name, size=m.group(4))
            if m.group(1) == "Receiving":
                self._set(phase="connected", note="Connected. Starting…")
                risky = Path(m.group(2) or "").suffix.lower() in RISKY
                if risky:
                    self._set(risky=True)
            return m.group(1) == "Receiving"
        if line.startswith("Sending (->") or line.startswith("Receiving (<-"):
            self._set(phase="connected", note="Connected. Starting…")
            return True
        if line.startswith("Resume ") or line.startswith("Overwrite "):
            if self.kind == "receive":
                self._answer_yes()
            self._set(note="Resuming where it stopped…")
            return True
        m = PROGRESS.search(line)
        if m:
            pct = int(m.group(1))
            detail = m.group(2)
            speed = detail.split(",")[1].strip() if "," in detail else ""
            self._set(phase="transferring", pct=pct, speed=speed, note="")
            return True
        low = line.lower()
        if "room is full" in low or "bad password" in low or "incorrect" in low:
            self._set(note="That code is already in use or wrong. Ask the sender for the code again.")
        return False

    def _deliver(self):
        """Move received items from the staging folder into the final folder, never overwriting."""
        staging = self._staging()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        saved, risky = [], False
        for item in sorted(staging.iterdir()):
            dest = unique_path(self.out_dir, item.name)
            shutil.move(str(item), str(dest))
            saved.append(dest.name)
            files = [dest] if dest.is_file() else [p for p in dest.rglob("*") if p.is_file()]
            risky = risky or any(p.suffix.lower() in RISKY for p in files)
        shutil.rmtree(staging, ignore_errors=True)
        self._set(saved=saved, risky=risky)
