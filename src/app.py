"""WinDrop desktop app: shows a QR code your iPhone scans to send and receive files over Wi-Fi."""
import json
import os
import queue
import secrets
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import qrcode

from server import DropServer, human, local_ips, safe_name
from torrent import TorrentManager

APP = "WinDrop"
VERSION = "1.1.1"
INBOX = Path.home() / "Downloads" / APP
OUTBOX = INBOX / "Send to iPhone"
CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home() / ".config")) / APP
CONFIG = CONFIG_DIR / "config.json"

BG, CARD, INK, DIM, BLUE = "#f6f7f9", "#ffffff", "#15171c", "#6b7280", "#2f6fec"


def resource(rel):
    base = getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)
    return str(Path(base) / rel)


def load_config():
    try:
        return json.loads(CONFIG.read_text())
    except Exception:
        return {}


def save_config(cfg):
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps(cfg, indent=2))
    except OSError:
        pass


def new_token():
    return secrets.token_hex(3)


def open_folder(path):
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class App:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.cfg = load_config()
        self.cfg.setdefault("token", new_token())
        self.cfg.setdefault("port", 8765)
        save_config(self.cfg)

        self.torrents = TorrentManager(OUTBOX / "Torrents", CONFIG_DIR, on_event=lambda *e: self.events.put(e))
        self.torrents_ok = self.torrents.start()
        self.server = DropServer(INBOX, OUTBOX, self.cfg["token"], self.cfg["port"],
                                 on_event=lambda *e: self.events.put(e), torrents=self.torrents)
        try:
            self.server.start()
        except OSError:
            messagebox.showerror(APP, "WinDrop couldn't start because the network port is in use.\n"
                                      "Close any other WinDrop window and try again.")
            self.torrents.stop()
            root.destroy()
            return

        self.connected = set()
        self.ips = local_ips()
        self.build_ui()
        self.refresh_qr()
        self.log(f"Ready. Files from your iPhone are saved to {INBOX}")
        if not self.torrents_ok:
            self.log("Torrent downloads are unavailable (download engine not found).")
        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.after(200, self.poll)

    # ---------- UI ----------
    def build_ui(self):
        r = self.root
        r.title(APP)
        r.configure(bg=BG)
        r.minsize(400, 600)
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

        wrap = tk.Frame(r, bg=BG, padx=22, pady=18)
        wrap.pack(fill="both", expand=True)

        tk.Label(wrap, text=APP, bg=BG, fg=INK, font=("Segoe UI Semibold", 20)).pack(anchor="w")
        tk.Label(wrap, text="Scan with your iPhone camera to connect", bg=BG, fg=DIM,
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 12))

        card = tk.Frame(wrap, bg=CARD, highlightthickness=1, highlightbackground="#e3e5ea", padx=16, pady=16)
        card.pack(fill="x")
        self.qr = tk.Canvas(card, width=230, height=230, bg="white", highlightthickness=0)
        self.qr.pack()

        self.addr = tk.StringVar()
        entry = ttk.Entry(card, textvariable=self.addr, state="readonly", justify="center", font=("Segoe UI", 10))
        entry.pack(fill="x", pady=(12, 4))

        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x")
        tk.Label(row, text="Network address", bg=CARD, fg=DIM, font=("Segoe UI", 9)).pack(side="left")
        self.ip_var = tk.StringVar(value=self.ips[0])
        combo = ttk.Combobox(row, textvariable=self.ip_var, values=self.ips, state="readonly", width=16)
        combo.pack(side="right")
        combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_qr())

        tk.Label(wrap, text="Your iPhone and this laptop must be on the same Wi-Fi.\n"
                            "Transfers stay on your network and use no mobile data.",
                 bg=BG, fg=DIM, font=("Segoe UI", 9), justify="left").pack(anchor="w", pady=(10, 12))

        btns = tk.Frame(wrap, bg=BG)
        btns.pack(fill="x")
        ttk.Button(btns, text="Send files to iPhone…", style="Accent.TButton",
                   command=self.add_files).pack(side="left", fill="x", expand=True, padx=(0, 6), ipady=4)
        ttk.Button(btns, text="Open received files",
                   command=lambda: open_folder(INBOX)).pack(side="left", fill="x", expand=True, padx=(6, 0), ipady=4)

        tk.Label(wrap, text="Activity", bg=BG, fg=INK, font=("Segoe UI Semibold", 11)).pack(anchor="w", pady=(16, 4))
        box = tk.Frame(wrap, bg=CARD, highlightthickness=1, highlightbackground="#e3e5ea")
        box.pack(fill="both", expand=True)
        self.activity = tk.Listbox(box, bg=CARD, fg=INK, borderwidth=0, highlightthickness=0,
                                   font=("Segoe UI", 9), activestyle="none", selectbackground="#dbe6fd",
                                   selectforeground=INK)
        sb = ttk.Scrollbar(box, command=self.activity.yview)
        self.activity.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.activity.pack(side="left", fill="both", expand=True, padx=8, pady=6)

        foot = tk.Frame(wrap, bg=BG)
        foot.pack(fill="x", pady=(10, 0))
        tk.Label(foot, text=f"v{VERSION}", bg=BG, fg=DIM, font=("Segoe UI", 8)).pack(side="left")
        ttk.Button(foot, text="New link", command=self.new_link).pack(side="right")
        ttk.Button(foot, text="Phone can't connect?", command=self.help_connect).pack(side="right", padx=(0, 6))

    def refresh_qr(self):
        url = self.server.url(self.ip_var.get())
        self.addr.set(url)
        qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(url)
        qr.make(fit=True)
        m = qr.get_matrix()
        n, size = len(m), 230
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
        if sys.platform == "win32" and getattr(sys, "frozen", False):
            if messagebox.askyesno(APP, "If your iPhone says the server stopped responding, Windows Firewall "
                                        "is usually blocking WinDrop.\n\nFix it now? Windows will ask for permission.\n\n"
                                        "Also check that your iPhone and laptop are on the same Wi-Fi or hotspot."):
                self.fix_firewall()
        else:
            messagebox.showinfo(APP, "Check that both devices are on the same Wi-Fi, and allow WinDrop "
                                     "through Windows Firewall on Private and Public networks.")

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
        if result > 32:
            self.log("Firewall fixed. Scan the QR code again on your iPhone.")
        else:
            self.log("Firewall fix was cancelled.")

    def new_link(self):
        if not messagebox.askyesno(APP, "Create a new link? Phones that connected before will need to scan the new QR code."):
            return
        self.cfg["token"] = new_token()
        save_config(self.cfg)
        self.server.token = self.cfg["token"]
        self.refresh_qr()
        self.log("New link created. Scan the QR code again on your iPhone.")

    def poll(self):
        try:
            while True:
                kind, name, extra = self.events.get_nowait()
                if kind == "received":
                    self.log(f"↓  Received  {name}  ({human(extra)})")
                elif kind == "sent":
                    self.log(f"↑  Sent to iPhone  {name}")
                elif kind == "queued":
                    self.log(f"•  Ready for iPhone  {name}  (tap Refresh in Safari)")
                elif kind == "connected":
                    if name not in self.connected:
                        self.connected.add(name)
                        self.log("📱  Phone connected")
                elif kind == "torrent_added":
                    self.log(f"⇣  Laptop download started  {name}")
                elif kind == "torrent_done":
                    self.log(f"✓  Download finished  {name}  ({human(extra)}). Ready for iPhone.")
                elif kind == "torrent_risky":
                    self.log(f"⚠  {name} contains a program file. Only open it if you trust the source.")
                elif kind == "torrent_error":
                    self.log(f"!  Download failed  {name}: {extra}")
                elif kind == "error":
                    self.log(f"!  Couldn't add {name}: {extra}")
        except queue.Empty:
            pass
        self.root.after(200, self.poll)

    def quit(self):
        self.server.stop()
        self.torrents.stop()
        self.root.destroy()


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
