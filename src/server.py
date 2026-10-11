"""WinDrop transfer server.

Runs a small web server on the laptop. The iPhone opens it in Safari over the
local Wi-Fi network, so files never leave your network and no mobile data is used.
"""
import hashlib
import json
import os
import re
import secrets
import socket
import sys
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from page import LOCKED_PAGE, MISSING_PAGE, PAGE

IO_CHUNK = 1024 * 1024
UPLOAD_CHUNK = 8 * 1024 * 1024   # size of each piece of a resumable upload
COOKIE = "wd"
HASH_TORRENT = re.compile(r"^[0-9a-f]{40}\.torrent$")  # aria2's internal copies, kept for resuming
RISKY = {".exe", ".msi", ".bat", ".cmd", ".scr", ".com", ".ps1", ".vbs", ".js", ".jar", ".lnk", ".pif", ".reg"}


def local_ips():
    """Return this computer's IPv4 addresses on local networks, best guess first."""
    ips = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packets are sent
        ips.append(s.getsockname()[0])
    except OSError:
        pass
    finally:
        s.close()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.append(info[4][0])
    except OSError:
        pass
    seen, result = set(), []
    for ip in ips:
        if ip in seen or ip.startswith("127.") or ip.startswith("169.254."):
            continue
        seen.add(ip)
        result.append(ip)
    return result or ["127.0.0.1"]


def safe_name(name):
    name = os.path.basename(name.replace("\\", "/")).strip().strip(".")
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    return name or "file"


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


class _HTTPServer(ThreadingHTTPServer):
    """On Windows, claim the port exclusively so no other program can answer in our place."""
    daemon_threads = True
    allow_reuse_address = sys.platform != "win32"
    request_queue_size = 64

    def server_bind(self):
        if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Upload:
    """A resumable upload, stored as a pre-sized .part file plus a list of finished pieces."""

    def __init__(self, folder, uid, name, size):
        self.uid, self.name, self.size = uid, name, size
        self.part = folder / f"{uid}.part"
        self.meta = folder / f"{uid}.json"
        self.total = (size + UPLOAD_CHUNK - 1) // UPLOAD_CHUNK
        self.done = set()
        self.lock = threading.Lock()
        if self.meta.exists() and self.part.exists() and self.part.stat().st_size == size:
            try:
                saved = json.loads(self.meta.read_text())
                if saved.get("size") == size:
                    self.done = {i for i in saved.get("done", []) if 0 <= i < self.total}
            except (OSError, ValueError):
                pass
        else:
            with open(self.part, "wb") as f:
                f.truncate(size)
        self.save()

    def save(self):
        self.meta.write_text(json.dumps({"name": self.name, "size": self.size, "done": sorted(self.done)}))

    def piece(self, i):
        start = i * UPLOAD_CHUNK
        return start, min(UPLOAD_CHUNK, self.size - start)


class DropServer:
    """Owns the HTTP server. `on_event(kind, name, extra)` is called from worker threads."""

    def __init__(self, inbox, outbox, token, port=8765, on_event=None, torrents=None):
        self.inbox, self.outbox, self.token = Path(inbox), Path(outbox), token
        self.partial = self.inbox / ".partial"
        self.port, self.on_event = port, on_event or (lambda *a: None)
        self.torrents = torrents
        self.lock = threading.Lock()
        self.uploads = {}
        self.httpd = None

    def start(self, tries=10):
        for d in (self.inbox, self.outbox, self.partial):
            d.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.kernel32.SetFileAttributesW(str(self.partial), 0x2)  # hidden
            except Exception:
                pass
        self._clean_old_partials()
        last_error = None
        for port in range(self.port, self.port + tries):
            try:
                self.httpd = _HTTPServer(("0.0.0.0", port), Handler)
                break
            except OSError as e:
                last_error = e
        if not self.httpd:
            raise last_error
        self.httpd.drop = self
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None

    def url(self, ip, with_key=True):
        base = f"http://{ip}:{self.port}/"
        return base + f"?k={self.token}" if with_key else base

    def _clean_old_partials(self, days=7):
        cutoff = time.time() - days * 86400
        for f in self.partial.glob("*"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                pass

    def unique_inbox_path(self, name):
        with self.lock:
            p = self.inbox / name
            stem, suffix, i = p.stem, p.suffix, 1
            while p.exists():
                p = self.inbox / f"{stem} ({i}){suffix}"
                i += 1
            p.touch()
            return p

    def get_upload(self, name, size, mtime):
        uid = hashlib.sha1(f"{name}|{size}|{mtime}".encode()).hexdigest()[:20]
        with self.lock:
            up = self.uploads.get(uid)
            if not up:
                up = self.uploads[uid] = Upload(self.partial, uid, name, size)
            return up

    def outbox_files(self):
        """Finished files in the outbox, including inside folders (e.g. torrents), newest first."""
        root = self.outbox
        items = []
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fn in files:
                if fn.startswith(".") or fn.endswith(".aria2") or HASH_TORRENT.match(fn):
                    continue
                p = Path(dirpath) / fn
                if self._downloading(p):
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                items.append({"name": p.relative_to(root).as_posix(), "size": st.st_size,
                              "risky": p.suffix.lower() in RISKY, "t": st.st_mtime})
        items.sort(key=lambda x: -x["t"])
        for it in items:
            del it["t"]
        return items

    def _downloading(self, p):
        """True while aria2 still owns this file (a .aria2 control file sits next to it or a parent)."""
        root = self.outbox.resolve()
        cur = p
        while True:
            if Path(str(cur) + ".aria2").exists():
                return True
            if cur.parent == cur or cur.resolve() == root:
                return False
            cur = cur.parent

    def outbox_path(self, rel):
        root = self.outbox.resolve()
        try:
            p = (root / rel).resolve()
        except (OSError, ValueError):
            return None
        if root not in p.parents or not p.is_file():
            return None
        if any(part.startswith(".") for part in p.relative_to(root).parts) or p.name.endswith(".aria2") \
                or HASH_TORRENT.match(p.name):
            return None
        if self._downloading(p):
            return None
        return p


class Handler(BaseHTTPRequestHandler):
    server_version = "WinDrop"
    protocol_version = "HTTP/1.1"   # keep-alive: faster for many small requests

    def log_message(self, fmt, *args):
        pass

    # ---- helpers ----
    def reply(self, code, body, ctype, headers=()):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def json(self, code, obj):
        self.reply(code, json.dumps(obj).encode(), "application/json")

    def deny(self):
        self.reply(403, LOCKED_PAGE.encode(), "text/html; charset=utf-8")

    def body_json(self, limit=64 * 1024):
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise ValueError("too large")
        return json.loads(self.rfile.read(n) or b"{}")

    def drain(self):
        """Discard an unread request body so the connection stays usable."""
        n = int(self.headers.get("Content-Length") or 0)
        while n > 0:
            chunk = self.rfile.read(min(IO_CHUNK, n))
            if not chunk:
                break
            n -= len(chunk)

    def auth(self, query):
        token = self.server.drop.token
        key = query.get("k", [""])[0]
        if key and secrets.compare_digest(key, token):
            return "query"
        jar = SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except Exception:
            return None
        if COOKIE in jar and secrets.compare_digest(jar[COOKIE].value, token):
            return "cookie"
        return None

    # ---- GET ----
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        drop = self.server.drop
        u = urlparse(self.path)
        path = u.path or "/"
        q = parse_qs(u.query)
        how = self.auth(q)

        if path in ("/favicon.ico", "/apple-touch-icon.png", "/apple-touch-icon-precomposed.png"):
            return self.reply(204, b"", "image/x-icon")

        if path == "/files":
            return self.json(200, drop.outbox_files()) if how else self.deny()

        if path == "/torrent/list":
            if not how:
                return self.deny()
            tm = drop.torrents
            if not tm or not tm.available:
                return self.json(200, {"available": False, "items": []})
            try:
                return self.json(200, {"available": True, "items": tm.list()})
            except Exception as e:
                return self.json(200, {"available": False, "items": [], "error": str(e)})

        if path.startswith("/dl/"):
            if not how:
                return self.deny()
            p = drop.outbox_path(unquote(path[4:]))
            if not p:
                return self.reply(404, MISSING_PAGE.encode(), "text/html; charset=utf-8")
            return self.send_file(p)

        # Any other address shows the main page.
        if not how:
            return self.deny()
        headers = []
        if how == "query":
            headers.append(("Set-Cookie", f"{COOKIE}={drop.token}; Max-Age=31536000; Path=/; SameSite=Lax"))
        drop.on_event("connected", self.headers.get("User-Agent", ""), 0)
        return self.reply(200, PAGE.encode(), "text/html; charset=utf-8", headers)

    def send_file(self, p):
        size = p.stat().st_size
        start, end, code = 0, size - 1, 200
        m = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range", "").strip())
        if m and size:
            a, b = m.groups()
            if a:
                start = int(a)
                end = min(int(b), size - 1) if b else size - 1
            elif b:
                start = max(0, size - int(b))
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            code = 206
        length = end - start + 1 if size else 0
        self.send_response(code)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(p.name))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD" or not length:
            return
        try:
            with open(p, "rb") as f:
                self.connection.sendfile(f, offset=start, count=length)
            if start == 0 and code == 200:
                self.server.drop.on_event("sent", p.name, size)
        except (ConnectionError, OSError):
            self.close_connection = True

    # ---- POST ----
    def do_POST(self):
        drop = self.server.drop
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if not self.auth(q):
            self.drain()
            self.close_connection = True
            return self.deny()
        try:
            if u.path == "/upload/init":
                return self.upload_init()
            if u.path == "/upload/chunk":
                return self.upload_chunk(q)
            if u.path == "/upload/done":
                return self.upload_done(q)
            if u.path == "/torrent/add":
                return self.torrent_add()
            if u.path == "/torrent/file":
                return self.torrent_file()
            if u.path == "/torrent/action":
                return self.torrent_action()
        except ValueError as e:
            self.close_connection = True
            return self.json(400, {"error": str(e)})
        except Exception as e:
            self.close_connection = True
            return self.json(500, {"error": f"Something went wrong on the laptop: {e}"})
        self.drain()
        self.json(404, {"error": "unknown address"})

    def upload_init(self):
        data = self.body_json()
        name = safe_name(str(data.get("name", "file")))
        size = int(data.get("size", -1))
        if size < 0:
            raise ValueError("bad size")
        up = self.server.drop.get_upload(name, size, str(data.get("mtime", "")))
        self.json(200, {"id": up.uid, "chunk": UPLOAD_CHUNK, "done": sorted(up.done)})

    def upload_chunk(self, q):
        drop = self.server.drop
        up = drop.uploads.get(q.get("id", [""])[0])
        if not up:
            self.drain()
            return self.json(404, {"error": "unknown upload, start again"})
        i = int(q.get("i", ["-1"])[0])
        if not 0 <= i < up.total:
            raise ValueError("bad piece")
        start, expected = up.piece(i)
        length = int(self.headers.get("Content-Length") or 0)
        if length != expected:
            raise ValueError("wrong piece size")
        remaining = length
        try:
            with open(up.part, "r+b") as f:
                f.seek(start)
                while remaining > 0:
                    chunk = self.rfile.read(min(IO_CHUNK, remaining))
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)
        except (ConnectionError, OSError):
            remaining = remaining or 1
        if remaining:
            self.close_connection = True
            return self.json(400, {"error": "incomplete piece"})
        with up.lock:
            up.done.add(i)
            up.save()
        self.json(200, {"ok": True})

    def upload_done(self, q):
        drop = self.server.drop
        self.drain()
        up = drop.uploads.get(q.get("id", [""])[0])
        if not up:
            return self.json(404, {"error": "unknown upload"})
        with up.lock:
            if len(up.done) < up.total:
                return self.json(409, {"error": "missing pieces", "done": sorted(up.done)})
            dest = drop.unique_inbox_path(up.name)
            os.replace(up.part, dest)
            up.meta.unlink(missing_ok=True)
        with drop.lock:
            drop.uploads.pop(up.uid, None)
        drop.on_event("received", dest.name, up.size)
        self.json(200, {"saved": dest.name})

    def _tm(self):
        tm = self.server.drop.torrents
        if not tm or not tm.available:
            raise ValueError("Torrent downloads aren't available on this laptop")
        return tm

    def torrent_add(self):
        uri = str(self.body_json().get("uri", ""))
        try:
            gid = self._tm().add_uri(uri)
        except RuntimeError as e:
            raise ValueError(str(e))
        self.json(200, {"gid": gid})

    def torrent_file(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 20 * 1024 * 1024:
            raise ValueError("That .torrent file is too large")
        data = self.rfile.read(n)
        name = safe_name(unquote(self.headers.get("X-Filename", "file.torrent")))
        try:
            gid = self._tm().add_torrent_file(data, name)
        except RuntimeError as e:
            raise ValueError(str(e))
        self.json(200, {"gid": gid})

    def torrent_action(self):
        data = self.body_json()
        try:
            self._tm().action(str(data.get("gid", "")), str(data.get("action", "")))
        except RuntimeError as e:
            raise ValueError(str(e))
        self.json(200, {"ok": True})
