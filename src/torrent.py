"""Torrent and link downloads for WinDrop, powered by the bundled aria2 engine.

aria2 runs as a hidden background process and is controlled over a private
JSON-RPC connection that only this computer can reach.
"""
import base64
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

RISKY = {".exe", ".msi", ".bat", ".cmd", ".scr", ".com", ".ps1", ".vbs", ".js", ".jar", ".lnk", ".pif", ".reg"}
KEYS = ["gid", "status", "totalLength", "completedLength", "downloadSpeed", "connections",
        "numSeeders", "files", "bittorrent", "errorMessage", "followedBy", "dir"]


def find_aria2():
    names = ["aria2c.exe", "aria2c"]
    bases = []
    if hasattr(sys, "_MEIPASS"):
        bases.append(Path(sys._MEIPASS) / "aria2")
    here = Path(__file__).resolve().parent
    bases += [here.parent / "vendor" / "aria2", here]
    for b in bases:
        for n in names:
            if (b / n).is_file():
                return b / n
    found = shutil.which("aria2c")
    return Path(found) if found else None


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TorrentManager:
    def __init__(self, download_dir, config_dir, on_event=None):
        self.dir = Path(download_dir)
        self.config_dir = Path(config_dir)
        self.on_event = on_event or (lambda *a: None)
        self.proc = None
        self.available = False
        self.secret = secrets.token_hex(16)
        self.url = None
        self.seen_done = set()
        self.rejected = {}
        self.handled = set()          # link downloads that were swapped for a torrent or rejected
        self.check_lock = threading.Lock()  # links that turned out to be web pages: gid -> summary
        self._stop = threading.Event()
        # Never send local RPC calls through a system proxy.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    # ---------- lifecycle ----------
    def start(self):
        src = find_aria2()
        if not src:
            return False
        exe = src
        if getattr(sys, "frozen", False):
            # Run from a fixed location so Windows Firewall only asks once.
            engine = self.config_dir / "engine" / src.name
            try:
                engine.parent.mkdir(parents=True, exist_ok=True)
                if not engine.exists() or engine.stat().st_size != src.stat().st_size:
                    shutil.copy2(src, engine)
                exe = engine
            except OSError:
                exe = src
        self.dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        session = self.config_dir / "aria2.session"
        session.touch(exist_ok=True)
        port = free_port()
        self.url = f"http://127.0.0.1:{port}/jsonrpc"
        args = [
            str(exe), "--enable-rpc", f"--rpc-listen-port={port}", "--rpc-listen-all=false",
            f"--rpc-secret={self.secret}", f"--dir={self.dir}",
            f"--input-file={session}", f"--save-session={session}", "--save-session-interval=30",
            f"--dht-file-path={self.config_dir / 'dht.dat'}",
            f"--stop-with-process={os.getpid()}",
            "--seed-time=0", "--follow-torrent=mem", "--bt-save-metadata=false",
            "--continue=true", "--auto-file-renaming=true", "--allow-overwrite=false",
            "--file-allocation=none", "--disk-cache=64M",
            "--max-concurrent-downloads=3", "--split=8", "--max-connection-per-server=8",
            "--enable-dht=true", "--bt-enable-lpd=true", "--enable-peer-exchange=true",
            "--console-log-level=error", "--summary-interval=0", "--quiet=true",
        ]
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            self.proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL, creationflags=flags)
        except OSError:
            return False
        for _ in range(50):
            try:
                self.call("aria2.getVersion")
                self.available = True
                break
            except Exception:
                if self.proc.poll() is not None:
                    return False
                time.sleep(0.1)
        if self.available:
            try:  # downloads restored from last time shouldn't announce themselves again
                self.seen_done = {t["gid"] for t in self._raw() if t.get("status") in ("complete", "error")}
            except Exception:
                pass
            threading.Thread(target=self._watch, daemon=True).start()
        return self.available

    def stop(self):
        self._stop.set()
        if self.proc and self.proc.poll() is None:
            try:
                self.call("aria2.saveSession")
                self.call("aria2.shutdown")
                self.proc.wait(timeout=3)
            except Exception:
                self.proc.kill()
        self.available = False

    # ---------- RPC ----------
    def call(self, method, *params):
        body = json.dumps({"jsonrpc": "2.0", "id": "wd", "method": method,
                           "params": [f"token:{self.secret}", *params]}).encode()
        req = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(req, timeout=5) as r:
                res = json.loads(r.read())
        except urllib.error.HTTPError as e:  # aria2 reports RPC errors as HTTP 400
            try:
                res = json.loads(e.read())
            except ValueError:
                raise RuntimeError(f"aria2 error {e.code}")
        if "error" in res:
            raise RuntimeError(res["error"].get("message", "aria2 error"))
        return res["result"]

    # ---------- actions ----------
    def add_uri(self, uri):
        uri = uri.strip()
        if not (uri.startswith("magnet:?") or uri.startswith("http://") or uri.startswith("https://")):
            raise ValueError("Paste a magnet link or a link starting with http:// or https://")
        gid = self.call("aria2.addUri", [uri])
        self.on_event("torrent_added", "magnet link" if uri.startswith("magnet:") else uri.rsplit("/", 1)[-1][:60], 0)
        return gid

    def add_torrent_file(self, data, name="file.torrent"):
        if not data.startswith(b"d"):
            raise ValueError("That doesn't look like a .torrent file")
        gid = self.call("aria2.addTorrent", base64.b64encode(data).decode())
        self.on_event("torrent_added", name, 0)
        return gid

    def action(self, gid, what):
        if gid in self.rejected:
            self.rejected.pop(gid, None)
            return
        if what == "pause":
            self.call("aria2.pause", gid)
        elif what == "resume":
            self.call("aria2.unpause", gid)
        elif what == "remove":
            info = self.call("aria2.tellStatus", gid, KEYS)
            if info.get("status") in ("active", "waiting", "paused"):
                try:
                    self.call("aria2.forceRemove", gid)
                except RuntimeError:
                    pass
                for _ in range(20):  # wait for aria2 to let go of the files
                    time.sleep(0.15)
                    try:
                        if self.call("aria2.tellStatus", gid, ["status"]).get("status") == "removed":
                            break
                    except RuntimeError:
                        break
                self._delete_partial(info)
            try:
                self.call("aria2.removeDownloadResult", gid)
            except RuntimeError:
                pass
        else:
            raise ValueError("Unknown action")

    def _delete_partial(self, info):
        """Remove half-downloaded files of a cancelled download (only inside our folder)."""
        root = self.dir.resolve()
        targets = set()
        name = (info.get("bittorrent") or {}).get("info", {}).get("name")
        if name:
            targets.add(Path(info.get("dir", self.dir)) / name)
        for f in info.get("files", []):
            if f.get("path") and not f["path"].startswith("[METADATA]"):
                targets.add(Path(f["path"]))
        for t in targets:
            try:
                t = t.resolve()
                if root not in t.parents:
                    continue
                for victim in (t, Path(str(t) + ".aria2")):
                    if victim.is_dir():
                        shutil.rmtree(victim, ignore_errors=True)
                    elif victim.exists():
                        victim.unlink()
            except OSError:
                pass

    def _inspect_finished(self, t):
        """Look inside a finished link download. A .torrent file starts the real download;
        a web page is discarded with a helpful message. Returns True if it was handled."""
        if t.get("bittorrent"):
            return False
        files = t.get("files") or []
        if len(files) != 1 or not files[0].get("path"):
            return False
        path = Path(files[0]["path"])
        try:
            if not path.is_file() or path.stat().st_size > 20 * 1024 * 1024:
                return False
            data = path.read_bytes()
        except OSError:
            return False
        head = data[:1024].lstrip().lower()
        if data.startswith(b"d") and b"4:info" in data:
            try:
                self.call("aria2.addTorrent", base64.b64encode(data).decode())
            except RuntimeError:
                return False
            self._forget(t["gid"], path)
            self.on_event("torrent_added", "torrent from link", 0)
            return True
        if head.startswith(b"<!doctype html") or head.startswith(b"<html") or b"<html" in head[:300]:
            self._forget(t["gid"], path)
            info = self.summarize(t)
            info.update(status="error", done=0, total=0, name=info["name"] or "Link",
                        error="That link opens a web page, not a download. On the website, long-press the "
                              "magnet or download button, copy that link, and paste it here.")
            self.rejected[t["gid"]] = info
            self.on_event("torrent_error", info["name"], "the link was a web page")
            return True
        return False

    def _forget(self, gid, path):
        try:
            path.unlink()
        except OSError:
            pass
        try:
            self.call("aria2.removeDownloadResult", gid)
        except RuntimeError:
            pass

    # ---------- status ----------
    def _raw(self):
        items = self.call("aria2.tellActive", KEYS)
        items += self.call("aria2.tellWaiting", 0, 200, KEYS)
        items += self.call("aria2.tellStopped", 0, 200, KEYS)
        return items

    @staticmethod
    def summarize(t):
        total, done = int(t.get("totalLength", 0)), int(t.get("completedLength", 0))
        speed = int(t.get("downloadSpeed", 0))
        files = t.get("files") or []
        first = files[0].get("path", "") if files else ""
        meta = first.startswith("[METADATA]")
        name = (t.get("bittorrent") or {}).get("info", {}).get("name")
        if not name:
            if meta:
                name = "Fetching torrent info…"
            elif first:
                name = os.path.basename(first)
            elif files and files[0].get("uris"):
                name = files[0]["uris"][0]["uri"].rsplit("/", 1)[-1] or "Download"
            else:
                name = "Download"
        risky = any(Path(f.get("path", "")).suffix.lower() in RISKY for f in files)
        return {
            "gid": t["gid"], "name": name, "status": t.get("status"), "total": total, "done": done,
            "speed": speed, "peers": int(t.get("connections", 0)), "meta": meta, "risky": risky,
            "eta": int((total - done) / speed) if speed > 0 and total > done else None,
            "error": t.get("errorMessage") if t.get("status") == "error" else None,
        }

    def list(self):
        if not self.available:
            return []
        raws = [t for t in self._raw() if not t.get("followedBy") and t.get("status") != "removed"]
        self._process(raws)
        if self.handled:
            raws = [t for t in self._raw() if not t.get("followedBy") and t.get("status") != "removed"]
        out = [self.summarize(t) for t in raws if t["gid"] not in self.handled]
        out += list(self.rejected.values())
        order = {"active": 0, "waiting": 1, "paused": 2, "error": 3, "complete": 4}
        out.sort(key=lambda x: order.get(x["status"], 5))
        return out

    def _process(self, raws):
        """Announce finished downloads and swap .torrent links for real torrents (thread-safe)."""
        with self.check_lock:
            for raw in raws:
                it = self.summarize(raw)
                key = it["gid"]
                if key in self.seen_done:
                    continue
                if it["status"] == "complete" and not it["meta"]:
                    self.seen_done.add(key)
                    if self._inspect_finished(raw):
                        self.handled.add(key)
                        continue
                    self.on_event("torrent_done", it["name"], it["total"])
                    if it["risky"]:
                        self.on_event("torrent_risky", it["name"], 0)
                elif it["status"] == "error":
                    self.seen_done.add(key)
                    self.on_event("torrent_error", it["name"], it["error"] or "failed")

    def _watch(self):
        while not self._stop.wait(1.5):
            try:
                raws = [t for t in self._raw() if not t.get("followedBy")]
            except Exception:
                if self.proc and self.proc.poll() is not None:
                    self.available = False
                    self.on_event("torrent_error", "The torrent engine stopped", 0)
                    return
                continue
            self._process(raws)
