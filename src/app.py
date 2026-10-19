"""WinDrop desktop app: shows a QR code your iPhone scans to send and receive files over Wi-Fi."""
import json
import os
import queue
import secrets
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import qrcode

from server import DropServer, human, local_ips, safe_name
from torrent import TorrentManager
import far

def is_packaged():
    """True when running as the Microsoft Store (MSIX) version."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        length = ctypes.c_uint(0)
        return ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(length), None) != 15700
    except Exception:
        return False


STORE = is_packaged()
APP = "WinDrop"                          # folder names stay the same in every edition
NAME = "WinDrop X" if STORE else "WinDrop"  # name shown to the user (matches the Store listing)
VERSION = "1.3.0"
INBOX = Path.home() / "Downloads" / APP
OUTBOX = INBOX / "Send to iPhone"
CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home() / ".config")) / APP
CONFIG = CONFIG_DIR / "config.json"
FAR_INBOX = INBOX / "From far away"   # files received from another laptop over the internet
FAR_WORK = INBOX / ".far"             # unfinished far transfers (kept so they can resume)

BG, CARD, INK, DIM, BLUE = "#f6f7f9", "#ffffff", "#15171c", "#6b7280", "#2f6fec"
WARN_BG, WARN_INK = "#fff4dc", "#7a4b00"


def resource(rel):
    base = getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)
    return str(Path(base) / rel)


def load_config():
    try:
        return json.loads(CONFIG.read_text())
    except Exception:
        return {}


_save_lock = threading.Lock()


def save_config(cfg):
    with _save_lock:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            tmp = CONFIG.with_suffix(".tmp")
            tmp.write_text(json.dumps(cfg, indent=2))
            os.replace(tmp, CONFIG)
        except OSError:
            pass


def new_token():
    return secrets.token_urlsafe(24)  # 32 characters: impossible to guess


def open_folder(path):
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def network_profiles():
    """Map each local IPv4 address to (network name, category) using Windows' own network profiles."""
    if sys.platform != "win32":
        return {}
    ps = ("Get-NetIPAddress -AddressFamily IPv4 | ForEach-Object { "
          "$p = Get-NetConnectionProfile -InterfaceIndex $_.InterfaceIndex -ErrorAction SilentlyContinue; "
          "if ($p) { '{0}|{1}|{2}' -f $_.IPAddress, $p.NetworkCategory, $p.Name } }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                             capture_output=True, text=True, timeout=15,
                             creationflags=subprocess.CREATE_NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    result = {}
    for line in out.splitlines():
        parts = line.strip().split("|", 2)
        if len(parts) == 3:
            result[parts[0]] = (parts[2], parts[1])
    return result


def ago(ts):
    s = max(0, time.time() - ts)
    if s < 120:
        return "just now"
    if s < 3600:
        return f"{int(s // 60)} min ago"
    if s < 86400:
        return f"{int(s // 3600)} h ago"
    return f"{int(s // 86400)} days ago"


class App:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.cfg = load_config()
        had_old_link = bool(self.cfg.get("token"))
        upgraded = len(self.cfg.get("token", "")) < 20
        if upgraded:
            self.cfg["token"] = new_token()
            self.cfg["devices"] = {}
        self.cfg.setdefault("port", 8765)
        self.cfg.setdefault("devices", {})
        self.cfg.setdefault("trusted_networks", [])
        self.cfg.setdefault("downloads_enabled", False)
        if STORE:
            self.cfg["downloads_enabled"] = False
        save_config(self.cfg)

        emit = lambda *e: self.events.put(e)
        self.torrents = TorrentManager(OUTBOX / "Torrents", CONFIG_DIR, on_event=emit)
        self.server = DropServer(INBOX, OUTBOX, self.cfg["token"], self.cfg["port"], on_event=emit,
                                 torrents=self.torrents, devices=self.cfg["devices"], on_change=self.save_devices)
        try:
            self.server.start()
        except OSError:
            messagebox.showerror(NAME, f"{NAME} couldn't start because the network port is in use.\n"
                                      "Close any other WinDrop window and try again.")
            root.destroy()
            return
        self.server.downloads_supported = not STORE
        self.server.name = NAME

        self.profiles = {}
        self.approvals, self.prompting = [], False
        self.far_jobs = []
        self.approval_window = None
        self.connected = set()
        self.ips = local_ips()
        self.build_ui()
        self.refresh_qr()
        self.log(f"Ready. Files from your iPhone are saved to {INBOX}")
        if upgraded and had_old_link:
            self.log("Security update: phones need to scan the new QR code once and be approved.")
        if self.cfg["downloads_enabled"]:
            self.set_downloads(True, quiet=True)
        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.after(200, self.poll)
        self.watch_networks()

    # ---------- UI ----------
    def build_ui(self):
        r = self.root
        r.title(NAME)
        r.configure(bg=BG)
        r.minsize(420, 560)
        try:
            r.iconbitmap(resource("assets/icon.ico"))
        except Exception:
            pass

        style = ttk.Style(r)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))
        style.configure("TCheckbutton", background=BG)

        wrap = tk.Frame(r, bg=BG, padx=20, pady=14)
        wrap.pack(fill="both", expand=True)

        tk.Label(wrap, text=NAME, bg=BG, fg=INK, font=("Segoe UI Semibold", 20)).pack(anchor="w")
        tk.Label(wrap, text="Scan with your iPhone camera to connect", bg=BG, fg=DIM,
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 8))

        # Public-network warning (hidden unless needed)
        self.warn = tk.Frame(wrap, bg=WARN_BG, padx=12, pady=10, highlightthickness=1, highlightbackground="#f0d9a8")
        self.warn_text = tk.Label(self.warn, bg=WARN_BG, fg=WARN_INK, font=("Segoe UI", 9), justify="left",
                                  wraplength=330, anchor="w")
        self.warn_text.pack(fill="x")
        wrow = tk.Frame(self.warn, bg=WARN_BG)
        wrow.pack(fill="x", pady=(8, 0))
        ttk.Button(wrow, text="Trust this network", command=self.trust_network).pack(side="right")
        self.warn_combo = ttk.Combobox(wrow, state="readonly", width=16)
        self.warn_combo.pack(side="left")
        self.warn_combo.bind("<<ComboboxSelected>>", lambda e: (self.ip_var.set(self.warn_combo.get()),
                                                               self.refresh_qr(), self.update_warning()))

        self.card = tk.Frame(wrap, bg=CARD, highlightthickness=1, highlightbackground="#e3e5ea", padx=14, pady=12)
        self.card.pack(fill="x")
        self.qr = tk.Canvas(self.card, width=190, height=190, bg="white", highlightthickness=0)
        self.qr.pack()

        self.addr = tk.StringVar()
        ttk.Entry(self.card, textvariable=self.addr, state="readonly", justify="center",
                  font=("Segoe UI", 9)).pack(fill="x", pady=(12, 4))

        row = tk.Frame(self.card, bg=CARD)
        row.pack(fill="x")
        tk.Label(row, text="Network address", bg=CARD, fg=DIM, font=("Segoe UI", 9)).pack(side="left")
        self.ip_var = tk.StringVar(value=self.ips[0])
        combo = self.combo = ttk.Combobox(row, textvariable=self.ip_var, values=self.ips, state="readonly", width=16)
        combo.pack(side="right")
        combo.bind("<<ComboboxSelected>>", lambda e: (self.refresh_qr(), self.update_warning()))

        tk.Label(wrap, text="New phones must be approved on this laptop before they can connect.\n"
                            "Transfers stay on your network and use no mobile data.",
                 bg=BG, fg=DIM, font=("Segoe UI", 9), justify="left").pack(anchor="w", pady=(10, 10))

        btns = tk.Frame(wrap, bg=BG)
        btns.pack(fill="x")
        ttk.Button(btns, text="Send files to iPhone…", style="Accent.TButton",
                   command=self.add_files).pack(side="left", fill="x", expand=True, padx=(0, 6), ipady=4)
        ttk.Button(btns, text="Open received files",
                   command=lambda: open_folder(INBOX)).pack(side="left", fill="x", expand=True, padx=(6, 0), ipady=4)
        far_row = tk.Frame(wrap, bg=BG)
        far_row.pack(fill="x", pady=(6, 0))
        ttk.Button(far_row, text="Send to a far laptop…",
                   command=self.far_send).pack(side="left", fill="x", expand=True, padx=(0, 6), ipady=2)
        ttk.Button(far_row, text="Receive with a code…",
                   command=self.far_receive).pack(side="left", fill="x", expand=True, padx=(6, 0), ipady=2)

        self.dl_var = tk.BooleanVar(value=self.cfg["downloads_enabled"])
        if not STORE:
            ttk.Checkbutton(wrap, text="Allow laptop downloads (torrents and links) from the iPhone",
                            variable=self.dl_var, command=lambda: self.set_downloads(self.dl_var.get())
                            ).pack(anchor="w", pady=(12, 0))

        tk.Label(wrap, text="Activity", bg=BG, fg=INK, font=("Segoe UI Semibold", 11)).pack(anchor="w", pady=(12, 4))
        box = tk.Frame(wrap, bg=CARD, highlightthickness=1, highlightbackground="#e3e5ea")
        box.pack(fill="both", expand=True)
        self.activity = tk.Listbox(box, bg=CARD, fg=INK, borderwidth=0, highlightthickness=0,
                                   font=("Segoe UI", 9), activestyle="none", selectbackground="#dbe6fd",
                                   selectforeground=INK, height=3)
        sb = ttk.Scrollbar(box, command=self.activity.yview)
        self.activity.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.activity.pack(side="left", fill="both", expand=True, padx=8, pady=6)

        foot = tk.Frame(wrap, bg=BG)
        foot.pack(fill="x", pady=(10, 0))
        tk.Label(foot, text=f"v{VERSION}", bg=BG, fg=DIM, font=("Segoe UI", 8)).pack(side="left")
        ttk.Button(foot, text="New link", command=self.new_link).pack(side="right")
        ttk.Button(foot, text="Devices", command=self.show_devices).pack(side="right", padx=(0, 6))
        ttk.Button(foot, text="Can't connect?", command=self.help_connect).pack(side="right", padx=(0, 6))

    def refresh_qr(self):
        url = self.server.url(self.ip_var.get())
        self.addr.set(url)
        qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(url)
        qr.make(fit=True)
        m = qr.get_matrix()
        n, size = len(m), 190
        cell = size // n
        off = (size - cell * n) // 2
        c = self.qr
        c.delete("all")
        for y, row in enumerate(m):
            for x, on in enumerate(row):
                if on:
                    c.create_rectangle(off + x * cell, off + y * cell, off + (x + 1) * cell, off + (y + 1) * cell,
                                       fill="black", outline="")

    def log(self, text):
        self.activity.insert(0, text)

    # ---------- public networks ----------
    def watch_networks(self):
        def work():
            profiles = network_profiles()
            self.events.put(("_profiles", profiles, 0))
        threading.Thread(target=work, daemon=True).start()
        self.root.after(20000, self.watch_networks)

    def apply_profiles(self, profiles):
        self.profiles = profiles
        trusted = set(self.cfg["trusted_networks"])
        self.server.public_block = {ip for ip, (name, cat) in profiles.items()
                                    if cat == "Public" and name not in trusted}
        current = local_ips()
        if current != self.ips:
            self.ips = current
            if self.ip_var.get() not in current:
                self.ip_var.set(current[0])
                self.refresh_qr()
        self.update_warning()

    def update_warning(self):
        ip = self.ip_var.get()
        self.combo.configure(values=self.ips)
        self.warn_combo.configure(values=self.ips)
        self.warn_combo.set(ip)
        if ip in self.server.public_block:
            name = self.profiles.get(ip, ("this network", ""))[0]
            self.warn_text.config(text=f"Windows marks “{name}” as a public network, so WinDrop is blocking "
                                       f"connections on it. If it's your own hotspot or home Wi-Fi, trust it. "
                                       f"Never trust café, airport or hotel Wi-Fi.")
            if not self.warn.winfo_ismapped():
                self.warn.pack(fill="x", before=self.card)
                self.card.pack_forget()  # the QR code can't work here until the network is trusted
        elif self.warn.winfo_ismapped():
            self.card.pack(fill="x", before=self.warn)
            self.warn.pack_forget()

    def trust_network(self):
        ip = self.ip_var.get()
        name = self.profiles.get(ip, ("", ""))[0]
        if not name:
            return
        if not messagebox.askyesno(NAME, f"Trust “{name}”?\n\nOnly do this for your own hotspot or home Wi-Fi. "
                                        f"Anyone on a trusted network can ask to connect (you still approve each device)."):
            return
        if name not in self.cfg["trusted_networks"]:
            self.cfg["trusted_networks"].append(name)
            save_config(self.cfg)
        self.apply_profiles(self.profiles)
        self.log(f"Trusted network: {name}")

    # ---------- devices ----------
    def save_devices(self):
        self.cfg["devices"] = dict(self.server.devices)
        save_config(self.cfg)

    def next_approval(self):
        if self.prompting or not self.approvals:
            return
        did, info = self.approvals.pop(0)
        if did not in self.server.pending:
            return self.root.after(50, self.next_approval)
        self.prompting = True
        allow = self.ask_allow(info)
        if allow:
            self.server.approve(did)
            self.log(f"✓  Allowed {info['name']} ({info['ip']})")
        else:
            self.server.deny(did)
            self.log(f"✕  Declined {info['name']} ({info['ip']})")
        self.prompting = False
        self.root.after(50, self.next_approval)

    def ask_allow(self, info):
        """Approval window with clear Allow / Don't allow buttons (matches the wording on the phone)."""
        r = self.root
        r.deiconify()
        dlg = tk.Toplevel(r)
        dlg.title(NAME)
        dlg.configure(bg="white")
        dlg.resizable(False, False)
        dlg.transient(r)
        try:
            dlg.iconbitmap(resource("assets/icon.ico"))
        except Exception:
            pass
        body = tk.Frame(dlg, bg="white", padx=22, pady=20)
        body.pack(fill="both")
        icon = tk.Canvas(body, width=34, height=48, bg="white", highlightthickness=0)
        icon.create_rectangle(4, 2, 30, 46, outline=BLUE, width=3)
        icon.create_line(13, 40, 21, 40, fill=BLUE, width=3)
        icon.pack(side="left", anchor="n", padx=(0, 16))
        text = tk.Frame(body, bg="white")
        text.pack(side="left", fill="x")
        tk.Label(text, text=f"{info['name']} wants to connect", bg="white", fg=INK,
                 font=("Segoe UI Semibold", 12)).pack(anchor="w")
        tk.Label(text, text=f"From {info['ip']} on your network.\nOnly allow your own devices or people you trust.",
                 bg="white", fg=DIM, font=("Segoe UI", 10), justify="left").pack(anchor="w", pady=(4, 0))
        bar = tk.Frame(dlg, bg="#f3f3f3", padx=16, pady=12)
        bar.pack(fill="x")
        result = {"allow": False}

        def finish(value):
            result["allow"] = value
            dlg.grab_release()
            dlg.destroy()
        ttk.Button(bar, text="Don't allow", command=lambda: finish(False)).pack(side="right")
        ttk.Button(bar, text="Allow", style="Accent.TButton", command=lambda: finish(True)).pack(side="right", padx=(0, 8))
        dlg.protocol("WM_DELETE_WINDOW", lambda: finish(False))
        dlg.bind("<Escape>", lambda e: finish(False))
        dlg.update_idletasks()
        x = r.winfo_rootx() + (r.winfo_width() - dlg.winfo_reqwidth()) // 2
        y = r.winfo_rooty() + (r.winfo_height() - dlg.winfo_reqheight()) // 3
        dlg.geometry(f"+{max(0, x)}+{max(0, y)}")
        dlg.attributes("-topmost", True)
        dlg.lift()
        dlg.focus_force()
        try:
            dlg.grab_set()
        except tk.TclError:
            pass
        r.bell()
        self.approval_window = dlg
        r.wait_window(dlg)
        self.approval_window = None
        return result["allow"]

    def show_devices(self):
        win = tk.Toplevel(self.root)
        win.title("Allowed devices")
        win.configure(bg=BG, padx=16, pady=14)
        win.transient(self.root)
        win.resizable(False, False)
        tk.Label(win, text="These devices can connect without asking again.\n"
                           "Devices unused for 30 days must be approved again.",
                 bg=BG, fg=DIM, font=("Segoe UI", 9), justify="left").pack(anchor="w", pady=(0, 8))
        lb = tk.Listbox(win, width=52, height=8, font=("Segoe UI", 9), activestyle="none")
        lb.pack(fill="both")
        ids = []

        def fill():
            lb.delete(0, "end")
            ids.clear()
            for did, d in sorted(self.server.devices.items(), key=lambda kv: -kv[1].get("last", 0)):
                ids.append(did)
                lb.insert("end", f"{d.get('name', 'Device')}   {d.get('ip', '')}   last used {ago(d.get('last', 0))}")
            if not ids:
                lb.insert("end", "No devices yet.")

        def remove():
            sel = lb.curselection()
            if sel and sel[0] < len(ids):
                self.server.forget(ids[sel[0]])
                self.log("Removed a device.")
                fill()

        def remove_all():
            if ids and messagebox.askyesno(NAME, "Remove all devices? Each one will need approval again.", parent=win):
                self.server.forget()
                self.log("Removed all devices.")
                fill()

        fill()
        row = tk.Frame(win, bg=BG)
        row.pack(fill="x", pady=(10, 0))
        ttk.Button(row, text="Remove", command=remove).pack(side="left")
        ttk.Button(row, text="Remove all", command=remove_all).pack(side="left", padx=6)
        ttk.Button(row, text="Close", command=win.destroy).pack(side="right")

    # ---------- laptop downloads ----------
    def set_downloads(self, on, quiet=False):
        if on and not self.torrents.available:
            if not self.torrents.start():
                self.dl_var.set(False)
                self.server.downloads_enabled = False
                if not quiet:
                    messagebox.showwarning(NAME, "The download engine couldn't start, so laptop downloads aren't available.")
                return
        elif not on and self.torrents.available:
            self.torrents.stop()
            self.torrents = TorrentManager(OUTBOX / "Torrents", CONFIG_DIR, on_event=lambda *e: self.events.put(e))
            self.server.torrents = self.torrents
        self.server.downloads_enabled = on
        self.cfg["downloads_enabled"] = on
        save_config(self.cfg)
        if not quiet:
            self.log("Laptop downloads turned on. They use this laptop's internet connection."
                     if on else "Laptop downloads turned off.")

    # ---------- actions ----------
    def add_files(self):
        paths = filedialog.askopenfilenames(title="Choose files to send to your iPhone")
        if not paths:
            return

        def copy():
            OUTBOX.mkdir(parents=True, exist_ok=True)
            for p in paths:
                src = Path(p)
                try:
                    shutil.copy2(src, OUTBOX / safe_name(src.name))
                    self.events.put(("queued", src.name, src.stat().st_size))
                except OSError as e:
                    self.events.put(("error", src.name, str(e)))
        threading.Thread(target=copy, daemon=True).start()

    def help_connect(self):
        if self.ip_var.get() in self.server.public_block:
            messagebox.showinfo(NAME, f"{NAME} is blocking this network because Windows marks it as public. "
                                     "If it's your own hotspot or home Wi-Fi, click “Trust this network” at the top.")
            return
        if STORE:
            messagebox.showinfo(NAME, "Check that your iPhone and this PC are on the same Wi-Fi or hotspot, "
                                      "then scan the QR code again.\n\nIf it still can't connect, restart the PC "
                                      "once so Windows applies the app's network permission.")
            return
        if sys.platform == "win32" and getattr(sys, "frozen", False):
            if messagebox.askyesno(NAME, "If your iPhone says the server stopped responding, Windows Firewall "
                                        "is usually blocking WinDrop.\n\nFix it now? Windows will ask for permission.\n\n"
                                        "Also check that your iPhone and laptop are on the same Wi-Fi or hotspot."):
                self.fix_firewall()
        else:
            messagebox.showinfo(NAME, "Check that both devices are on the same Wi-Fi or hotspot, and that WinDrop "
                                     "is allowed through Windows Firewall.")

    def fix_firewall(self):
        import ctypes
        exe = sys.executable
        engine = CONFIG_DIR / "engine" / "aria2c.exe"
        cmd = (f'/c netsh advfirewall firewall delete rule name=all program="{exe}" & '
               f'netsh advfirewall firewall add rule name="WinDrop" dir=in action=allow '
               f'program="{exe}" enable=yes profile=any & '
               f'netsh advfirewall firewall delete rule name=all program="{engine}" & '
               f'netsh advfirewall firewall add rule name="WinDrop downloads" dir=in action=allow '
               f'program="{engine}" enable=yes profile=any')
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", cmd, None, 0)
        self.log("Firewall fixed. Scan the QR code again on your iPhone." if result > 32
                 else "Firewall fix was cancelled.")

    def new_link(self):
        if not messagebox.askyesno(NAME, "Create a new link and remove all allowed devices?\n\n"
                                        "Every phone will need to scan the new QR code and be approved again."):
            return
        self.cfg["token"] = new_token()
        self.server.token = self.cfg["token"]
        self.server.forget()
        save_config(self.cfg)
        self.refresh_qr()
        self.log("New link created and all devices removed.")

    def poll(self):
        try:
            while True:
                kind, name, extra = self.events.get_nowait()
                if kind == "_profiles":
                    self.apply_profiles(name)
                elif kind == "device_request":
                    self.approvals.append((name, extra))
                    self.log(f"?  {extra['name']} ({extra['ip']}) is asking to connect")
                    self.root.after(10, self.next_approval)
                elif kind == "lockout":
                    self.log(f"⚠  Blocked {name} for 15 minutes after repeated wrong keys")
                elif kind == "received":
                    self.log(f"↓  Received  {name}  ({human(extra)})")
                elif kind == "sent":
                    self.log(f"↑  Sent to iPhone  {name}")
                elif kind == "queued":
                    self.log(f"•  Ready for iPhone  {name}  (tap Refresh in Safari)")
                elif kind == "connected":
                    pass
                elif kind == "torrent_added":
                    self.log(f"⇣  Laptop download started  {name}")
                elif kind == "torrent_done":
                    self.log(f"✓  Download finished  {name}  ({human(extra)}). Ready for iPhone.")
                elif kind == "torrent_risky":
                    self.log(f"⚠  {name} contains a program file. Only open it if you trust the source.")
                elif kind == "torrent_error":
                    self.log(f"!  Download failed  {name}: {extra}")
                elif kind == "far_done":
                    st = extra
                    if name == "send":
                        self.log(f"⇄  Sent to a far laptop  {st.get('name', '')}  ({st.get('size', '')})")
                    else:
                        self.log(f"⇄  Received from a far laptop  {', '.join(st.get('saved', []))}  ({st.get('size', '')})")
                        if st.get("risky"):
                            self.log("⚠  It contains a program file. Only open it if you trust the sender.")
                elif kind == "far_failed":
                    self.log(f"!  Far transfer failed: {extra}")
                elif kind == "error":
                    self.log(f"!  Couldn't add {name}: {extra}")
        except queue.Empty:
            pass
        self.root.after(200, self.poll)

    # ---------- far transfers (laptop to laptop over the internet) ----------
    def far_ready(self):
        if far.find_croc():
            return True
        messagebox.showwarning(NAME, "Far transfers aren't available in this copy of WinDrop "
                                     "(the transfer engine is missing). Please reinstall the latest version.")
        return False

    def far_send(self):
        if not self.far_ready():
            return
        paths = filedialog.askopenfilenames(title="Choose files to send to a far laptop")
        if not paths:
            return
        job = far.FarJob("send", far.new_code(), paths=paths, relay=self.cfg.get("far_relay"),
                         on_event=lambda *e: self.events.put(e)).start()
        self.far_jobs.append(job)
        FarWindow(self, job, paths)

    def far_receive(self):
        if not self.far_ready():
            return
        code = ask_code(self.root)
        if not code:
            return
        job = far.FarJob("receive", code, out_dir=FAR_INBOX, work_dir=FAR_WORK, relay=self.cfg.get("far_relay"),
                         on_event=lambda *e: self.events.put(e)).start()
        self.far_jobs.append(job)
        FarWindow(self, job)

    def quit(self):
        active = [j for j in self.far_jobs if not j.finished]
        if active and not messagebox.askyesno(NAME, "A far transfer is still running.\n\nQuit anyway? "
                                                     "It can continue later if both sides use the same code again."):
            return
        for j in active:
            j.cancel()
        self.server.stop()
        self.torrents.stop()
        self.root.destroy()


def on_phone_hotspot():
    """iPhone hotspots hand out 172.20.10.x; Android hotspots commonly 192.168.43.x."""
    return any(ip.startswith("172.20.10.") or ip.startswith("192.168.43.") for ip in local_ips())


def ask_code(root):
    """Small window asking for the code the sender gave you. Returns the cleaned code or None."""
    dlg = tk.Toplevel(root)
    dlg.title(f"{NAME} · Receive with a code")
    dlg.configure(bg=BG, padx=22, pady=18)
    dlg.resizable(False, False)
    dlg.transient(root)
    tk.Label(dlg, text="Receive from a far laptop", bg=BG, fg=INK, font=("Segoe UI Semibold", 14)).pack(anchor="w")
    tk.Label(dlg, text="Type the code shown on the sender's WinDrop, for example 4821-amber-river-stone.",
             bg=BG, fg=DIM, font=("Segoe UI", 9), wraplength=360, justify="left").pack(anchor="w", pady=(4, 10))
    var = tk.StringVar()
    entry = ttk.Entry(dlg, textvariable=var, font=("Consolas", 14), width=28)
    entry.pack(fill="x", ipady=4)
    err = tk.Label(dlg, text="", bg=BG, fg="#b42318", font=("Segoe UI", 9))
    err.pack(anchor="w", pady=(4, 0))
    result = {"code": None}

    def go(event=None):
        code = far.clean_code(var.get())
        if not code:
            err.config(text="Enter the full code from the sender (at least 6 letters or numbers).")
            return
        result["code"] = code
        dlg.destroy()
    row = tk.Frame(dlg, bg=BG)
    row.pack(fill="x", pady=(10, 0))
    ttk.Button(row, text="Cancel", command=dlg.destroy).pack(side="right")
    ttk.Button(row, text="Receive", style="Accent.TButton", command=go).pack(side="right", padx=(0, 8))
    entry.bind("<Return>", go)
    var.trace_add("write", lambda *a: err.config(text=""))
    entry.focus_set()
    dlg.grab_set()
    root.wait_window(dlg)
    return result["code"]


class FarWindow:
    """Shows one far transfer: the code to share (sending), progress, and the result."""
    VERB = {"send": "Sending", "receive": "Receiving"}

    def __init__(self, app, job, paths=None):
        self.app, self.job = app, job
        w = self.win = tk.Toplevel(app.root)
        w.title(f"{NAME} · {'Send to a far laptop' if job.kind == 'send' else 'Receive from a far laptop'}")
        w.configure(bg=BG, padx=22, pady=18)
        w.resizable(False, False)
        try:
            w.iconbitmap(resource("assets/icon.ico"))
        except Exception:
            pass
        title = "Send to a far laptop" if job.kind == "send" else "Receiving from a far laptop"
        tk.Label(w, text=title, bg=BG, fg=INK, font=("Segoe UI Semibold", 14)).pack(anchor="w")
        if job.kind == "send":
            names = [Path(p).name for p in paths]
            what = names[0] if len(names) == 1 else f"{len(names)} files"
            tk.Label(w, text=f"{what}\n\nOn the other laptop, open WinDrop, click “Receive with a code” and type:",
                     bg=BG, fg=DIM, font=("Segoe UI", 9), wraplength=380, justify="left").pack(anchor="w", pady=(4, 8))
            row = tk.Frame(w, bg=BG)
            row.pack(fill="x")
            code = tk.Entry(row, font=("Consolas", 14, "bold"), relief="flat", justify="center",
                            width=len(job.code) + 2, readonlybackground=CARD, fg=INK,
                            highlightthickness=1, highlightbackground="#e3e5ea")
            code.insert(0, job.code)
            code.config(state="readonly")
            code.pack(side="left", fill="x", expand=True, ipady=8)
            self.copy_btn = ttk.Button(row, text="Copy", command=self.copy)
            self.copy_btn.pack(side="left", padx=(8, 0))
            if on_phone_hotspot():
                tk.Label(w, text="⚠ This laptop is on a phone hotspot, so sending uses mobile data (the whole file "
                                 "size). Connect to home Wi-Fi to avoid that.", bg=WARN_BG, fg=WARN_INK,
                         font=("Segoe UI", 9), wraplength=370, justify="left", padx=8, pady=6).pack(fill="x", pady=(10, 0))
        else:
            tk.Label(w, text=f"Code: {job.code}", bg=BG, fg=DIM, font=("Consolas", 10)).pack(anchor="w", pady=(4, 0))
        style = ttk.Style(w)
        style.configure("Far.Horizontal.TProgressbar", background=BLUE, troughcolor="#e3e5ea",
                        bordercolor="#e3e5ea", lightcolor=BLUE, darkcolor=BLUE)
        self.bar = ttk.Progressbar(w, length=380, maximum=100, style="Far.Horizontal.TProgressbar")
        self.bar.pack(fill="x", pady=(14, 6))
        self.status = tk.Label(w, text="Connecting…", bg=BG, fg=INK, font=("Segoe UI", 10), wraplength=380,
                               justify="left", anchor="w")
        self.status.pack(fill="x")
        self.detail = tk.Label(w, text="", bg=BG, fg=DIM, font=("Segoe UI", 9), anchor="w")
        self.detail.pack(fill="x", pady=(2, 0))
        tk.Label(w, text="Keep both laptops on and connected until it finishes. If the connection drops, "
                         "it continues automatically.", bg=BG, fg=DIM, font=("Segoe UI", 8), wraplength=380,
                 justify="left").pack(anchor="w", pady=(10, 0))
        self.buttons = tk.Frame(w, bg=BG)
        self.buttons.pack(fill="x", pady=(12, 0))
        self.cancel_btn = ttk.Button(self.buttons, text="Cancel", command=self.cancel)
        self.cancel_btn.pack(side="right")
        w.protocol("WM_DELETE_WINDOW", self.close)
        self.tick()

    def copy(self):
        self.win.clipboard_clear()
        self.win.clipboard_append(self.job.code)
        self.copy_btn.config(text="Copied ✓")
        self.win.after(1500, lambda: self.copy_btn.winfo_exists() and self.copy_btn.config(text="Copy"))

    def cancel(self):
        if self.job.finished:
            return self.win.destroy()
        if messagebox.askyesno(NAME, "Stop this transfer?", parent=self.win):
            self.job.cancel()

    def close(self):
        if self.job.finished:
            self.win.destroy()
        else:
            self.cancel()

    def tick(self):
        if not self.win.winfo_exists():
            return
        s = self.job.snapshot()
        phase, pct = s["phase"], s["pct"]
        verb = self.VERB[self.job.kind]
        text = {
            "starting": "Connecting…", "connecting": "Connecting…",
            "preparing": f"Getting the file ready… {pct}%",
            "connected": "Connected. Starting…",
            "transferring": f"{verb}… {pct}%",
            "verifying": "Checking the file arrived intact…",
            "checking": "Checking what was already received…",
            "done": ("Sent! The other laptop has the file." if self.job.kind == "send"
                     else "Received and saved in Downloads\\WinDrop\\From far away."),
            "cancelled": "Cancelled.",
        }.get(phase, s["note"] or phase)
        if phase in ("waiting", "retrying", "failed"):
            text = s["note"]
        self.status.config(text=text)
        self.bar["value"] = pct if phase in ("transferring", "done", "preparing") else (100 if phase == "verifying" else 0)
        bits = [b for b in (s["name"], s["size"], s["speed"]) if b]
        self.detail.config(text="  ·  ".join(bits))
        if self.job.finished:
            self.cancel_btn.config(text="Close")
            if phase == "done" and self.job.kind == "receive":
                ttk.Button(self.buttons, text="Open folder", style="Accent.TButton",
                           command=lambda: open_folder(FAR_INBOX)).pack(side="right", padx=(0, 8))
                if s.get("risky"):
                    self.detail.config(text="⚠ Contains a program file. Only open it if you trust the sender.")
            return
        self.win.after(300, self.tick)


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
