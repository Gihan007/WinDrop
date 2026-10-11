"""The web page your iPhone sees, plus small notice pages."""

_NOTICE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>WinDrop</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0f1115;color:#eef0f4;
font:17px/1.5 -apple-system,system-ui,sans-serif;text-align:center;padding:24px}p{color:#8b91a0;max-width:30ch}</style>
</head><body><div><h1>WinDrop</h1><p>%s</p></div></body></html>"""

LOCKED_PAGE = _NOTICE % "Open WinDrop on your laptop and scan its QR code with your iPhone camera to connect."
MISSING_PAGE = _NOTICE % "That file is no longer on the laptop. Go back and tap Refresh list."

PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="WinDrop">
<title>WinDrop</title>
<style>
  :root { --bg:#0f1115; --card:#181b22; --line:#262a33; --ink:#eef0f4; --dim:#8b91a0; --blue:#3d8bfd; --ok:#3ccf8e; --bad:#ff5c5c; --warn:#f5b84b; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink); font:16px/1.45 -apple-system, system-ui, sans-serif;
         padding:calc(20px + env(safe-area-inset-top)) 18px calc(36px + env(safe-area-inset-bottom)); }
  main { max-width:520px; margin:0 auto; }
  h1 { font-size:28px; margin:0 0 4px; }
  p.sub { color:var(--dim); margin:0 0 22px; }
  section { background:var(--card); border-radius:16px; padding:18px; margin-bottom:16px; }
  h2 { font-size:17px; margin:0 0 4px; }
  .hint { color:var(--dim); font-size:14px; margin:0 0 12px; }
  label.pick, button.main { display:block; width:100%; text-align:center; background:var(--blue); color:#fff; font:600 16px -apple-system, system-ui, sans-serif;
         padding:15px; border-radius:12px; border:0; cursor:pointer; }
  button.main:disabled { opacity:.5; }
  input[type=file] { display:none; }
  textarea { width:100%; min-height:64px; background:#0f1115; color:var(--ink); border:1px solid #333845; border-radius:12px;
         padding:12px; font:15px/1.35 -apple-system, system-ui, sans-serif; resize:vertical; margin-bottom:10px; }
  .row2 { display:flex; gap:10px; align-items:center; }
  .row2 button.main { flex:1; }
  .link { color:var(--blue); background:none; border:0; font-size:15px; padding:8px 4px; cursor:pointer; white-space:nowrap; }
  .msg { font-size:14px; margin-top:8px; min-height:1px; }
  .msg.bad { color:var(--bad); }
  ul { list-style:none; margin:12px 0 0; padding:0; }
  li { padding:10px 0; border-top:1px solid var(--line); display:flex; flex-wrap:wrap; gap:4px 10px; align-items:center; }
  li:first-child { border-top:0; }
  .n, a.f { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--ink); }
  a.f { color:var(--blue); text-decoration:none; }
  .s { color:var(--dim); font-size:14px; font-variant-numeric:tabular-nums; }
  .bar { flex-basis:100%; height:4px; background:var(--line); border-radius:2px; overflow:hidden; }
  .bar i { display:block; height:100%; width:0; background:var(--blue); transition:width .3s; }
  li.ok .bar i { background:var(--ok); } li.ok .s { color:var(--ok); }
  li.bad .bar i { background:var(--bad); } li.bad .s { color:var(--bad); }
  li.paused .bar i { background:var(--dim); }
  .acts { flex-basis:100%; display:flex; gap:14px; }
  .acts button { background:none; border:0; color:var(--blue); font-size:14px; padding:2px 0; cursor:pointer; }
  .warn { flex-basis:100%; color:var(--warn); font-size:13px; }
  .empty { color:var(--dim); font-size:15px; display:block; }
  button.refresh { background:none; border:1px solid #333845; color:var(--ink); border-radius:10px; padding:8px 14px; font-size:15px; margin-top:12px; }
</style></head>
<body><main>
  <h1>WinDrop</h1>
  <p class="sub">Keep this page open and your screen on while files transfer.</p>

  <section>
    <h2>iPhone to laptop</h2>
    <p class="hint">Big files resume automatically if the connection drops.</p>
    <label class="pick" for="pick">Choose photos or files</label>
    <input id="pick" type="file" multiple>
    <ul id="queue"></ul>
  </section>

  <section id="tsec">
    <h2>Download on laptop</h2>
    <p class="hint">Paste a magnet link, torrent link or any download link. The laptop downloads it using its own internet connection, then it appears below.</p>
    <textarea id="link" placeholder="magnet:?xt=…  or  https://…" autocapitalize="off" autocorrect="off" spellcheck="false"></textarea>
    <div class="row2">
      <button class="main" id="go">Download</button>
      <label class="link" for="tfile">Use .torrent file</label>
      <input id="tfile" type="file">
    </div>
    <div class="msg" id="tmsg"></div>
    <ul id="tlist"></ul>
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
const u = p => K ? p + (p.includes('?') ? '&' : '?') + 'k=' + encodeURIComponent(K) : p;
const $ = id => document.getElementById(id);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const size = n => n < 1024 ? n + ' B' : n < 1048576 ? (n/1024).toFixed(1) + ' KB' : n < 1073741824 ? (n/1048576).toFixed(1) + ' MB' : (n/1073741824).toFixed(2) + ' GB';
const eta = s => !isFinite(s) || s <= 0 ? '' : s < 60 ? Math.ceil(s) + 's left' : s < 3600 ? Math.ceil(s/60) + ' min left' : (s/3600).toFixed(1) + ' h left';
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
function postJSON(path, obj) { return fetch(u(path), { method:'POST', headers:{ 'Content-Type':'application/json' }, body: JSON.stringify(obj) }); }

/* ---------- iPhone to laptop: parallel, resumable ---------- */
const WORKERS = 4, FILES_AT_ONCE = 3;
$('pick').addEventListener('change', async () => {
  const files = [...$('pick').files]; $('pick').value = '';
  const todo = files.slice();
  await Promise.all(Array.from({ length: Math.min(FILES_AT_ONCE, todo.length) }, async () => { while (todo.length) await sendFile(todo.shift()); }));
});

async function sendFile(file) {
  const row = el('li'), bar = el('i'), st = el('span', 's', 'Waiting');
  const b = el('div', 'bar'); b.append(bar);
  row.append(el('span', 'n', file.name), st, b); $('queue').prepend(row);
  const fail = msg => { st.textContent = msg; row.classList.add('bad'); };

  let init;
  for (let tries = 0; ; tries++) {
    try {
      const r = await postJSON('/upload/init', { name: file.name, size: file.size, mtime: file.lastModified || 0 });
      if (r.status === 403) return fail('Link expired. Scan the QR code again.');
      if (!r.ok) throw 0;
      init = await r.json(); break;
    } catch (e) { if (tries > 5) return fail('Could not reach the laptop'); st.textContent = 'Connecting…'; await sleep(1500); }
  }
  const CS = init.chunk, total = Math.ceil(file.size / CS), done = new Set(init.done);
  const pieceLen = i => Math.min(CS, file.size - i * CS);
  let sent = [...done].reduce((s, i) => s + pieceLen(i), 0);
  const queue = []; for (let i = 0; i < total; i++) if (!done.has(i)) queue.push(i);
  const inflight = new Map(), samples = [];
  let note = done.size ? 'Resuming… ' : '';
  const bytesNow = () => { let n = sent; for (const v of inflight.values()) n += v; return n; };
  const tick = () => {
    const now = performance.now(), n = bytesNow();
    samples.push([now, n]); while (samples.length > 2 && now - samples[0][0] > 5000) samples.shift();
    const [t0, n0] = samples[0], sp = now > t0 ? (n - n0) / ((now - t0) / 1000) : 0;
    const pct = file.size ? n / file.size * 100 : 100;
    bar.style.width = pct + '%';
    st.textContent = note + Math.floor(pct) + '%' + (sp > 0 ? '  ' + size(sp) + '/s  ' + eta((file.size - n) / sp) : '');
  };
  const timer = setInterval(tick, 500); tick();

  const sendPiece = i => new Promise((res, rej) => {
    const x = new XMLHttpRequest();
    x.open('POST', u('/upload/chunk?id=' + init.id + '&i=' + i));
    x.upload.onprogress = e => inflight.set(i, e.loaded);
    x.onload = () => { inflight.delete(i);
      if (x.status === 200) { sent += pieceLen(i); res(); }
      else if (x.status === 403 || x.status === 404) rej(Object.assign(new Error('fatal'), { fatal: x.status }));
      else rej(new Error('retry')); };
    x.onerror = x.ontimeout = () => { inflight.delete(i); rej(new Error('net')); };
    x.send(file.slice(i * CS, i * CS + pieceLen(i)));
  });
  const worker = async () => {
    while (queue.length) {
      const i = queue.shift();
      for (let tries = 1; ; tries++) {
        try { await sendPiece(i); note = ''; break; }
        catch (e) {
          if (e.fatal || tries > 30) throw e;
          note = 'Reconnecting… '; await sleep(Math.min(8000, 800 * tries));
        }
      }
    }
  };
  try {
    if (queue.length) await Promise.all(Array.from({ length: Math.min(WORKERS, queue.length) }, worker));
    const r = await fetch(u('/upload/done?id=' + init.id), { method: 'POST' });
    if (!r.ok) throw new Error('finish');
    clearInterval(timer);
    bar.style.width = '100%'; st.textContent = 'Sent, ' + size(file.size); row.classList.add('ok');
  } catch (e) {
    clearInterval(timer);
    fail(e.fatal === 403 ? 'Link expired. Scan the QR code again.' : 'Paused. Choose the same file again to resume.');
  }
}

/* ---------- Download on laptop ---------- */
const tmsg = (text, bad) => { $('tmsg').textContent = text || ''; $('tmsg').className = 'msg' + (bad ? ' bad' : ''); };
$('go').onclick = async () => {
  const v = $('link').value.trim(); if (!v) return tmsg('Paste a link first.', true);
  $('go').disabled = true;
  try {
    const r = await postJSON('/torrent/add', { uri: v }), j = await r.json();
    if (!r.ok) tmsg(j.error || 'Could not start the download.', true); else { $('link').value = ''; tmsg('Started on the laptop.'); }
  } catch (e) { tmsg('Could not reach the laptop.', true); }
  $('go').disabled = false; loadTorrents();
};
$('tfile').addEventListener('change', async () => {
  const f = $('tfile').files[0]; $('tfile').value = ''; if (!f) return;
  try {
    const r = await fetch(u('/torrent/file'), { method: 'POST', headers: { 'X-Filename': encodeURIComponent(f.name) }, body: f }), j = await r.json();
    if (!r.ok) tmsg(j.error || 'Could not use that file.', true); else tmsg('Started on the laptop.');
  } catch (e) { tmsg('Could not reach the laptop.', true); }
  loadTorrents();
});

const finished = new Set(); let firstLoad = true;
async function loadTorrents() {
  let j;
  try { const r = await fetch(u('/torrent/list')); if (!r.ok) return; j = await r.json(); } catch (e) { return; }
  const list = $('tlist');
  if (!j.available) { $('go').disabled = true; list.innerHTML = ''; list.append(el('li', 'empty', 'Downloads on the laptop aren\'t available in this copy of WinDrop.')); return; }
  $('go').disabled = false;
  list.innerHTML = '';
  let newDone = false;
  for (const t of j.items) {
    const row = el('li'), bar = el('i'), b = el('div', 'bar'); b.append(bar);
    const pct = t.total ? t.done / t.total * 100 : 0;
    bar.style.width = (t.status === 'complete' ? 100 : pct) + '%';
    let text;
    if (t.meta && t.status !== 'error') text = 'Finding peers… ' + t.peers + ' connected';
    else if (t.status === 'active') text = Math.floor(pct) + '%  ' + size(t.speed) + '/s  ' + eta(t.eta) + '  ' + t.peers + ' peers';
    else if (t.status === 'waiting') text = 'Queued';
    else if (t.status === 'paused') { text = 'Paused, ' + Math.floor(pct) + '%'; row.classList.add('paused'); }
    else if (t.status === 'complete') { text = 'Done, ' + size(t.total) + '. Ready below.'; row.classList.add('ok');
      if (!finished.has(t.gid)) { finished.add(t.gid); if (!firstLoad) newDone = true; } }
    else { text = 'Failed: ' + (t.error || 'unknown error'); row.classList.add('bad'); }
    row.append(el('span', 'n', t.name), b, el('span', 's', text));
    if (t.risky) row.append(el('span', 'warn', '⚠ Contains a program file. Only open it if you trust where it came from.'));
    const acts = el('div', 'acts');
    const act = (label, action) => { const btn = el('button', null, label); btn.onclick = async () => { btn.disabled = true; await postJSON('/torrent/action', { gid: t.gid, action }); loadTorrents(); }; acts.append(btn); };
    if (t.status === 'active' || t.status === 'waiting') act('Pause', 'pause');
    if (t.status === 'paused') act('Resume', 'resume');
    if (t.status === 'complete' || t.status === 'error') act('Clear', 'remove');
    else act('Cancel', 'remove');
    row.append(acts); list.append(row);
  }
  firstLoad = false;
  if (newDone) loadFiles();
}

/* ---------- Laptop to iPhone ---------- */
async function loadFiles() {
  const out = $('out');
  try {
    const r = await fetch(u('/files'));
    if (r.status === 403) { out.innerHTML = ''; out.append(el('li', 'empty', 'Link expired. Scan the QR code in WinDrop again.')); return; }
    const files = await r.json();
    out.innerHTML = '';
    if (!files.length) { out.append(el('li', 'empty', 'Nothing here yet. On the laptop, click "Send files to iPhone", or download something above.')); return; }
    for (const f of files) {
      const li = el('li'), a = el('a', 'f', f.name.replace(/^Torrents\//, ''));
      a.href = u('/dl/' + f.name.split('/').map(encodeURIComponent).join('/')); a.download = f.name.split('/').pop();
      li.append(a, el('span', 's', size(f.size)));
      if (f.risky) li.append(el('span', 'warn', '⚠ Program file. Only open it if you trust where it came from.'));
      out.append(li);
    }
  } catch (e) { out.innerHTML = ''; out.append(el('li', 'empty', 'Could not reach the laptop.')); }
}
$('refresh').onclick = loadFiles;
document.addEventListener('visibilitychange', () => { if (!document.hidden) { loadFiles(); loadTorrents(); } });
setInterval(() => { if (!document.hidden) loadTorrents(); }, 1500);
loadFiles(); loadTorrents();
</script>
</body></html>
"""
