"""WinDrop transfer server.

Runs a small web server on the laptop. The iPhone opens it in Safari over the
local Wi-Fi network, so files never leave your network and no mobile data is used.
"""
import json
import os
import re
import secrets
import socket
import sys
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlparse

CHUNK = 1024 * 1024
COOKIE = "wd"


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

    def server_bind(self):
        if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class DropServer:
    """Owns the HTTP server. `on_event(kind, name, size)` is called from worker threads."""

    def __init__(self, inbox, outbox, token, port=8765, on_event=None):
        self.inbox, self.outbox, self.token = inbox, outbox, token
        self.port, self.on_event = port, on_event or (lambda *a: None)
        self.lock = threading.Lock()
        self.httpd = None

    def start(self, tries=10):
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.outbox.mkdir(parents=True, exist_ok=True)
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

    def unique_inbox_path(self, name):
        with self.lock:
            p = self.inbox / name
            stem, suffix, i = p.stem, p.suffix, 1
            while p.exists():
                p = self.inbox / f"{stem} ({i}){suffix}"
                i += 1
            p.touch()
            return p


class Handler(BaseHTTPRequestHandler):
    server_version = "WinDrop"

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
        self.wfile.write(body)

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

    # ---- routes ----
    def deny(self):
        self.reply(403, LOCKED_PAGE.encode(), "text/html; charset=utf-8")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_GET(self):
        drop = self.server.drop
        u = urlparse(self.path)
        path = u.path or "/"
        how = self.auth(parse_qs(u.query))

        if path in ("/favicon.ico", "/apple-touch-icon.png", "/apple-touch-icon-precomposed.png"):
            return self.reply(204, b"", "image/x-icon")

        if path == "/files":
            if not how:
                return self.deny()
            files = [{"name": f.name, "size": f.stat().st_size}
                     for f in drop.outbox.iterdir() if f.is_file() and not f.name.startswith(".")]
            files.sort(key=lambda x: x["name"].lower())
            return self.reply(200, json.dumps(files).encode(), "application/json")

        if path.startswith("/dl/"):
            if not how:
                return self.deny()
            name = safe_name(unquote(path[4:]))
            p = drop.outbox / name
            if not p.is_file():
                return self.reply(404, MISSING_PAGE.encode(), "text/html; charset=utf-8")
            size = p.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(name))
            self.end_headers()
            try:
                with open(p, "rb") as f:
                    while chunk := f.read(CHUNK):
                        self.wfile.write(chunk)
                drop.on_event("sent", name, size)
            except (ConnectionError, OSError):
                pass
            return

        # Any other address shows the main page, so odd browser behaviour can't cause "Not found".
        if not how:
            return self.deny()
        headers = []
        if how == "query":
            headers.append(("Set-Cookie", f"{COOKIE}={drop.token}; Max-Age=31536000; Path=/; SameSite=Lax"))
        drop.on_event("connected", self.headers.get("User-Agent", ""), 0)
        return self.reply(200, PAGE.encode(), "text/html; charset=utf-8", headers)

    def do_POST(self):
        drop = self.server.drop
        u = urlparse(self.path)
        if not self.auth(parse_qs(u.query)):
            return self.deny()
        if u.path != "/upload":
            return self.reply(404, MISSING_PAGE.encode(), "text/html; charset=utf-8")

        name = safe_name(unquote(self.headers.get("X-Filename", "file")))
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        dest = drop.unique_inbox_path(name)
        remaining = length
        try:
            with open(dest, "wb") as f:
                while remaining > 0:
                    chunk = self.rfile.read(min(CHUNK, remaining))
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)
        except (ConnectionError, OSError):
            remaining = remaining or 1
        if remaining > 0 or length == 0:
            dest.unlink(missing_ok=True)
            return self.reply(400, b'{"error": "incomplete"}', "application/json")
        drop.on_event("received", dest.name, length)
        self.reply(200, json.dumps({"saved": dest.name}).encode(), "application/json")


LOCKED_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>WinDrop</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0f1115;color:#eef0f4;
font:17px/1.5 -apple-system,system-ui,sans-serif;text-align:center;padding:24px}p{color:#8b91a0;max-width:30ch}</style>
</head><body><div><h1>WinDrop</h1><p>Open WinDrop on your laptop and scan its QR code with your iPhone camera to connect.</p></div></body></html>"""

MISSING_PAGE = LOCKED_PAGE.replace(
    "Open WinDrop on your laptop and scan its QR code with your iPhone camera to connect.",
    "That file is no longer on the laptop. Go back and tap Refresh list.")

PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="WinDrop">
<title>WinDrop</title>
<style>
  :root { --bg:#0f1115; --card:#181b22; --line:#262a33; --ink:#eef0f4; --dim:#8b91a0; --blue:#3d8bfd; --ok:#3ccf8e; --bad:#ff5c5c; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink); font:16px/1.45 -apple-system, system-ui, sans-serif;
         padding:calc(20px + env(safe-area-inset-top)) 18px calc(36px + env(safe-area-inset-bottom)); }
  main { max-width:520px; margin:0 auto; }
  h1 { font-size:28px; margin:0 0 4px; }
  p.sub { color:var(--dim); margin:0 0 22px; }
  section { background:var(--card); border-radius:16px; padding:18px; margin-bottom:16px; }
  h2 { font-size:17px; margin:0 0 12px; }
  label.pick { display:block; text-align:center; background:var(--blue); color:#fff; font-weight:600; padding:16px; border-radius:12px; cursor:pointer; }
  input[type=file] { display:none; }
  ul { list-style:none; margin:12px 0 0; padding:0; }
  li { padding:10px 0; border-top:1px solid var(--line); display:flex; flex-wrap:wrap; gap:4px 10px; align-items:center; }
  li:first-child { border-top:0; }
  .n, a { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--ink); }
  a { color:var(--blue); text-decoration:none; }
  .s { color:var(--dim); font-size:14px; }
  .bar { flex-basis:100%; height:4px; background:var(--line); border-radius:2px; overflow:hidden; }
  .bar i { display:block; height:100%; width:0; background:var(--blue); transition:width .15s; }
  li.ok .bar i { background:var(--ok); } li.ok .s { color:var(--ok); }
  li.bad .bar i { background:var(--bad); } li.bad .s { color:var(--bad); }
  .empty { color:var(--dim); font-size:15px; display:block; }
  button.refresh { background:none; border:1px solid #333845; color:var(--ink); border-radius:10px; padding:8px 14px; font-size:15px; margin-top:12px; }
</style></head>
<body><main>
  <h1>WinDrop</h1>
  <p class="sub">Keep this page open while files transfer.</p>
  <section>
    <h2>iPhone to laptop</h2>
    <label class="pick" for="pick">Choose photos or files</label>
    <input id="pick" type="file" multiple>
    <ul id="queue"></ul>
  </section>
  <section>
    <h2>Laptop to iPhone</h2>
    <ul id="out"><li class="empty">Loading…</li></ul>
    <button class="refresh" id="refresh">Refresh list</button>
  </section>
</main>
<script>
const K = new URLSearchParams(location.search).get('k') || (() => { try { return localStorage.getItem('wdk') || ''; } catch (e) { return ''; } })();
try { if (K) localStorage.setItem('wdk', K); } catch (e) {}
const Q = K ? '?k=' + encodeURIComponent(K) : '';
const pick = document.getElementById('pick'), queue = document.getElementById('queue');
const size = n => n < 1024 ? n + ' B' : n < 1048576 ? (n/1024).toFixed(1) + ' KB' : n < 1073741824 ? (n/1048576).toFixed(1) + ' MB' : (n/1073741824).toFixed(2) + ' GB';

pick.addEventListener('change', () => {
  const files = [...pick.files];
  files.reduce((p, f) => p.then(() => send(f)), Promise.resolve()).then(() => { pick.value = ''; });
});

function send(file) {
  return new Promise(done => {
    const row = document.createElement('li');
    row.innerHTML = '<span class="n"></span><span class="s">Waiting</span><div class="bar"><i></i></div>';
    row.querySelector('.n').textContent = file.name;
    queue.prepend(row);
    const bar = row.querySelector('i'), st = row.querySelector('.s');
    const x = new XMLHttpRequest();
    x.open('POST', '/upload' + Q);
    x.setRequestHeader('X-Filename', encodeURIComponent(file.name));
    x.upload.onprogress = e => { if (e.lengthComputable) { const p = e.loaded / e.total * 100; bar.style.width = p + '%'; st.textContent = Math.round(p) + '%'; } };
    x.onload = () => {
      if (x.status === 200) { bar.style.width = '100%'; st.textContent = 'Sent, ' + size(file.size); row.classList.add('ok'); }
      else if (x.status === 403) { st.textContent = 'Link expired. Scan the QR code again.'; row.classList.add('bad'); }
      else { st.textContent = 'Failed'; row.classList.add('bad'); }
      done();
    };
    x.onerror = () => { st.textContent = 'Failed. Is WinDrop still open on the laptop?'; row.classList.add('bad'); done(); };
    x.send(file);
  });
}

async function loadFiles() {
  const out = document.getElementById('out');
  try {
    const r = await fetch('/files' + Q);
    if (r.status === 403) { out.innerHTML = '<li class="empty">Link expired. Scan the QR code in WinDrop again.</li>'; return; }
    const files = await r.json();
    out.innerHTML = '';
    if (!files.length) { out.innerHTML = '<li class="empty">Nothing here yet. On the laptop, click "Send files to iPhone", then tap Refresh.</li>'; return; }
    for (const f of files) {
      const li = document.createElement('li'), a = document.createElement('a'), s = document.createElement('span');
      a.href = '/dl/' + encodeURIComponent(f.name) + Q; a.textContent = f.name; a.download = f.name;
      s.className = 's'; s.textContent = size(f.size);
      li.append(a, s); out.append(li);
    }
  } catch (e) { out.innerHTML = '<li class="empty">Could not reach the laptop.</li>'; }
}
document.getElementById('refresh').onclick = loadFiles;
document.addEventListener('visibilitychange', () => { if (!document.hidden) loadFiles(); });
loadFiles();
</script>
</body></html>
"""
