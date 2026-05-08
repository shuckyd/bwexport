"""Tkinter GUI for Bitwarden per-collection export.

Designed to run on Windows (the typical MSP deployment target). Built for the
client-handover workflow: pick a collection, get a Bitwarden-compatible CSV
the client can re-import elsewhere.

Security model is identical to the CLI sibling (see bwexport.core): API key in
the OS credential store, master password interactive every unlock, BW_SESSION
held only in memory, output CSV ACL-restricted to the current user.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
import tkinter as tk
from pathlib import Path
from queue import Empty, Queue
from tkinter import filedialog, messagebox, ttk

from bwexport import core

APP_NAME = "bwexport"
APP_DIR = Path(os.environ.get("APPDATA") or Path.home() / ".config") / APP_NAME
CONFIG_PATH = APP_DIR / "config.json"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg: dict):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-").lower() or "export"


# --- Modal dialogs ---

class ApiKeyDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Bitwarden API Key")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        self.result = None

        frm = ttk.Frame(self, padding=16)
        frm.grid(row=0, column=0)

        ttk.Label(
            frm,
            text="Get your API key from the web vault: Account settings → Security → Keys → View API key.",
            wraplength=420, justify="left",
        ).grid(row=0, column=0, columnspan=2, pady=(0, 12), sticky="w")

        ttk.Label(frm, text="client_id:").grid(row=1, column=0, sticky="e", padx=4, pady=2)
        self.cid_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.cid_var, width=46, show="•").grid(row=1, column=1, pady=2)

        ttk.Label(frm, text="client_secret:").grid(row=2, column=0, sticky="e", padx=4, pady=2)
        self.csec_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.csec_var, width=46, show="•").grid(row=2, column=1, pady=2)

        existing_cid, _ = core.keyring_get_api_key()
        ttk.Label(
            frm,
            text=f"Existing key on file: client_id ending …{existing_cid[-6:]}" if existing_cid else "No key currently stored.",
            foreground="gray",
        ).grid(row=3, column=0, columnspan=2, pady=(8, 0), sticky="w")

        btns = ttk.Frame(frm)
        btns.grid(row=4, column=0, columnspan=2, pady=(16, 0))
        ttk.Button(btns, text="Save", command=self._save).grid(row=0, column=0, padx=4)
        ttk.Button(btns, text="Forget stored key", command=self._forget).grid(row=0, column=1, padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).grid(row=0, column=2, padx=4)

        self.bind("<Return>", lambda e: self._save())
        self.bind("<Escape>", lambda e: self.destroy())

    def _save(self):
        cid = self.cid_var.get().strip()
        csec = self.csec_var.get().strip()
        if not cid or not csec:
            messagebox.showerror("Missing fields", "Both client_id and client_secret are required.", parent=self)
            return
        try:
            core.keyring_set_api_key(cid, csec)
            self.result = "saved"
        except core.BWError as e:
            messagebox.showerror("Error", str(e), parent=self)
            return
        self.destroy()

    def _forget(self):
        if messagebox.askyesno("Forget API key", "Remove the stored API key from the credential store?", parent=self):
            core.keyring_delete_api_key()
            self.result = "deleted"
            self.destroy()


class MasterPasswordDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Unlock Vault")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        self.password: str | None = None

        frm = ttk.Frame(self, padding=16)
        frm.grid(row=0, column=0)

        ttk.Label(frm, text="Bitwarden master password:").grid(row=0, column=0, sticky="w")
        self.pw_var = tk.StringVar()
        entry = ttk.Entry(frm, textvariable=self.pw_var, show="•", width=40)
        entry.grid(row=1, column=0, pady=(4, 12))
        entry.focus_set()

        btns = ttk.Frame(frm)
        btns.grid(row=2, column=0)
        ttk.Button(btns, text="Unlock", command=self._ok).grid(row=0, column=0, padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).grid(row=0, column=1, padx=4)

        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())

    def _ok(self):
        self.password = self.pw_var.get()
        self.destroy()


# --- Main window ---

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Bitwarden Client Export")
        self.geometry("680x560")
        self.minsize(560, 480)

        self.cfg = load_config()
        self.session: str | None = None
        self.fresh_login = False
        self.collections: list[dict] = []
        self.events: Queue = Queue()
        self._busy = False
        self._visible_collections: list[dict] = []

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(80, self._poll_events)

        try:
            core.ensure_bw_installed()
        except core.BWError as e:
            self.after(150, lambda: messagebox.showerror("bw CLI missing", str(e), parent=self))

    def _build_ui(self):
        for c in range(2):
            self.columnconfigure(c, weight=1)
        self.rowconfigure(3, weight=1)

        sf = ttk.LabelFrame(self, text="Server", padding=8)
        sf.grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=(8, 4))
        sf.columnconfigure(1, weight=1)

        ttk.Label(sf, text="Server URL:").grid(row=0, column=0, sticky="e", padx=4, pady=2)
        self.server_var = tk.StringVar(value=self.cfg.get("server", ""))
        ttk.Entry(sf, textvariable=self.server_var).grid(row=0, column=1, sticky="ew", pady=2)

        ttk.Label(sf, text="Organization ID:").grid(row=1, column=0, sticky="e", padx=4, pady=2)
        self.org_var = tk.StringVar(value=self.cfg.get("org_id", ""))
        ttk.Entry(sf, textvariable=self.org_var).grid(row=1, column=1, sticky="ew", pady=2)

        ttk.Button(sf, text="Save settings", command=self._save_settings).grid(
            row=0, column=2, rowspan=2, padx=(8, 0)
        )

        af = ttk.Frame(self, padding=(8, 4))
        af.grid(row=1, column=0, columnspan=2, sticky="ew")
        af.columnconfigure(3, weight=1)

        self.unlock_btn = ttk.Button(af, text="Unlock vault", command=self._on_unlock)
        self.unlock_btn.grid(row=0, column=0, padx=(0, 4))

        self.lock_btn = ttk.Button(af, text="Lock", command=self._on_lock, state="disabled")
        self.lock_btn.grid(row=0, column=1, padx=4)

        ttk.Button(af, text="API key…", command=self._on_api_key).grid(row=0, column=2, padx=4)

        self.status_var = tk.StringVar(value="Locked.")
        ttk.Label(af, textvariable=self.status_var, anchor="e", foreground="gray").grid(
            row=0, column=3, sticky="ew", padx=(8, 0)
        )

        ff = ttk.Frame(self, padding=(8, 4))
        ff.grid(row=2, column=0, columnspan=2, sticky="ew")
        ff.columnconfigure(1, weight=1)
        ttk.Label(ff, text="Filter:").grid(row=0, column=0, padx=(0, 4))
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._refresh_list())
        ttk.Entry(ff, textvariable=self.filter_var).grid(row=0, column=1, sticky="ew")

        lf = ttk.LabelFrame(self, text="Collections", padding=4)
        lf.grid(row=3, column=0, columnspan=2, sticky="nsew", padx=8, pady=4)
        lf.columnconfigure(0, weight=1)
        lf.rowconfigure(0, weight=1)

        self.listbox = tk.Listbox(lf, exportselection=False, activestyle="dotbox")
        self.listbox.grid(row=0, column=0, sticky="nsew")
        self.listbox.bind("<<ListboxSelect>>", lambda e: self._update_export_button())
        self.listbox.bind("<Double-Button-1>", lambda e: self._on_export())

        sb = ttk.Scrollbar(lf, orient="vertical", command=self.listbox.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.listbox.configure(yscrollcommand=sb.set)

        ef = ttk.Frame(self, padding=(8, 4))
        ef.grid(row=4, column=0, columnspan=2, sticky="ew")
        self.export_btn = ttk.Button(ef, text="Export selected to CSV…", command=self._on_export, state="disabled")
        self.export_btn.grid(row=0, column=0)

        log_frame = ttk.LabelFrame(self, text="Log", padding=4)
        log_frame.grid(row=5, column=0, columnspan=2, sticky="ew", padx=8, pady=(4, 8))
        log_frame.columnconfigure(0, weight=1)
        self.log = tk.Text(log_frame, height=6, wrap="word", state="disabled", font=("Consolas", 9))
        self.log.grid(row=0, column=0, sticky="ew")

    # --- Background work + event loop ---

    def _poll_events(self):
        while True:
            try:
                fn, args = self.events.get_nowait()
            except Empty:
                break
            try:
                fn(*args)
            except Exception as e:
                self._log(f"!! handler error: {e}")
        self.after(80, self._poll_events)

    def _run_bg(self, work, on_success=None, on_error=None, status="Working…"):
        if self._busy:
            self._log("(busy — wait for current operation to finish)")
            return
        self._busy = True
        self._set_status(status)
        self._set_buttons_busy(True)

        def thread_main():
            try:
                result = work()
            except Exception as e:
                self.events.put((self._after_bg_error, (e, on_error)))
            else:
                self.events.put((self._after_bg_success, (result, on_success)))

        threading.Thread(target=thread_main, daemon=True).start()

    def _after_bg_success(self, result, on_success):
        self._busy = False
        self._set_buttons_busy(False)
        if on_success:
            on_success(result)

    def _after_bg_error(self, exc, on_error):
        self._busy = False
        self._set_buttons_busy(False)
        msg = str(exc) if str(exc) else exc.__class__.__name__
        self._log(f"!! {msg}")
        if on_error:
            on_error(exc)
        else:
            messagebox.showerror("Error", msg, parent=self)
        self._refresh_status()

    def _set_buttons_busy(self, busy: bool):
        self.unlock_btn.configure(state="disabled" if (busy or self.session) else "normal")
        self.lock_btn.configure(state="disabled" if (busy or not self.session) else "normal")
        self._update_export_button(force_disable=busy)

    # --- Actions ---

    def _save_settings(self):
        server = self.server_var.get().strip()
        org = self.org_var.get().strip()
        if not server or not org:
            messagebox.showerror("Missing", "Server URL and Organization ID are both required.", parent=self)
            return
        self.cfg["server"] = server
        self.cfg["org_id"] = org
        save_config(self.cfg)
        self._log(f"Saved settings to {CONFIG_PATH}")

    def _on_api_key(self):
        ApiKeyDialog(self).wait_window()

    def _on_unlock(self):
        server = self.server_var.get().strip()
        org = self.org_var.get().strip()
        if not server or not org:
            messagebox.showerror("Missing settings", "Set the server URL and organization ID first.", parent=self)
            return

        cid, csec = core.keyring_get_api_key()
        if not cid or not csec:
            messagebox.showinfo(
                "API key needed",
                "No Bitwarden API key is stored. Open API key… and add one before unlocking.",
                parent=self,
            )
            return

        dlg = MasterPasswordDialog(self)
        dlg.wait_window()
        master = dlg.password
        if not master:
            return

        def work():
            core.configure_server(server)
            fresh = core.status().get("status") == "unauthenticated"
            if fresh:
                core.login_apikey(cid, csec)
            session = core.unlock(master)
            core.sync(session)
            cols = core.list_org_collections(session, org)
            return fresh, session, cols

        def done(result):
            nonlocal master
            del master
            self.fresh_login, self.session, self.collections = result
            self.collections.sort(key=lambda c: c["name"].lower())
            self._refresh_list()
            self._refresh_status()
            self._log(f"Unlocked. Loaded {len(self.collections)} collection(s).")

        self._run_bg(work, on_success=done, status="Unlocking and syncing…")

    def _on_lock(self):
        if not self.session:
            return
        session, fresh = self.session, self.fresh_login
        self.session = None
        self.fresh_login = False
        self.collections = []
        self._refresh_list()
        self._refresh_status()

        def work():
            core.lock(session)
            if fresh:
                core.logout()
            return None

        self._run_bg(work, on_success=lambda _: self._log("Vault locked."), status="Locking…")

    def _on_export(self):
        sel = self.listbox.curselection()
        if not sel or not self.session:
            return
        col = self._visible_collections[sel[0]]
        org = self.org_var.get().strip()
        session = self.session

        default_name = f"{safe_filename(col['name'])}-{dt.date.today().isoformat()}.csv"
        out = filedialog.asksaveasfilename(
            parent=self,
            title=f"Save '{col['name']}' as CSV",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")],
        )
        if not out:
            return

        def work():
            items = core.list_collection_items(session, org, col["id"])
            core.write_csv(items, col["name"], out)
            return len(items), out

        def done(result):
            n, path = result
            self._log(f"Exported {n} item(s) from '{col['name']}' → {path}")
            messagebox.showinfo(
                "Export complete",
                f"Wrote {n} item(s) to:\n{path}\n\n"
                "Reminder: this CSV contains plaintext passwords. "
                "Encrypt before transmission and shred after handover.",
                parent=self,
            )

        self._run_bg(work, on_success=done, status=f"Exporting '{col['name']}'…")

    # --- View helpers ---

    def _refresh_list(self):
        q = self.filter_var.get()
        self._visible_collections = core.filter_collections(self.collections, q)
        self.listbox.delete(0, tk.END)
        for c in self._visible_collections:
            self.listbox.insert(tk.END, c["name"])
        self._update_export_button()

    def _update_export_button(self, force_disable: bool = False):
        ok = bool(self.session) and bool(self.listbox.curselection()) and not force_disable and not self._busy
        self.export_btn.configure(state="normal" if ok else "disabled")

    def _refresh_status(self):
        if self.session:
            self.status_var.set(f"Unlocked · {len(self.collections)} collection(s).")
            self.unlock_btn.configure(state="disabled")
            self.lock_btn.configure(state="normal")
        else:
            self.status_var.set("Locked.")
            self.unlock_btn.configure(state="normal")
            self.lock_btn.configure(state="disabled")

    def _set_status(self, text: str):
        self.status_var.set(text)

    def _log(self, line: str):
        self.log.configure(state="normal")
        self.log.insert(tk.END, f"{dt.datetime.now().strftime('%H:%M:%S')}  {line}\n")
        self.log.see(tk.END)
        self.log.configure(state="disabled")

    def _on_close(self):
        if self.session:
            session, fresh = self.session, self.fresh_login
            try:
                core.lock(session)
                if fresh:
                    core.logout()
            except Exception:
                pass
        self.destroy()


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
