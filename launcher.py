"""Feather Prep desktop launcher; its hardware inventory is read-only."""
import logging
import os
from pathlib import Path
import shutil
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from urllib.parse import urlparse
import webbrowser

from agent import cloud
from agent.core import Agent
from agent.server import make_http, main as server_main


APP_NAME = "FeatherOS"


def app_data_dir():
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / APP_NAME


def bundled_source_dir():
    # PyInstaller extracts embedded resources here; in a source checkout this
    # resolves to the checkout root.
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    bundled = root / "feather-source"
    return bundled if bundled.is_dir() else root


def seed_editable_source(source_dir):
    """Persist bundled editable source once without replacing user edits."""
    seed = bundled_source_dir()
    target = Path(source_dir)
    for origin in seed.rglob("*"):
        if not origin.is_file() or origin.suffix.lower() not in {".py", ".ps1", ".html", ".md"}:
            continue
        relative = origin.relative_to(seed)
        destination = target / relative
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, destination)
    target.mkdir(parents=True, exist_ok=True)


class FeatherPrep:
    def __init__(self):
        self.home = app_data_dir()
        self.data_dir = self.home / "data"
        self.source_dir = self.home / "source"
        self.home.mkdir(parents=True, exist_ok=True)
        seed_editable_source(self.source_dir)

        logging.basicConfig(filename=self.home / "feather.log", level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(message)s")
        self.agent = Agent(self.data_dir, self.source_dir)
        self.http = make_http(self.agent)
        self.stop_event = threading.Event()
        self.http_thread = threading.Thread(target=self.http.serve_forever,
                                            name="feather-local-dashboard", daemon=True)
        self.http_thread.start()
        self.ai_thread = None
        if cloud.configured():
            self.ai_thread = threading.Thread(target=cloud.worker,
                                              args=(self.agent, self.stop_event), daemon=True)
            self.ai_thread.start()

        self.root = tk.Tk()
        self.root.title("Feather Prep")
        self.root.geometry("460x225")
        self.root.resizable(False, False)
        frame = ttk.Frame(self.root, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Feather Prep", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Your existing Windows installation is untouched.",
                  wraplength=410).pack(anchor="w", pady=(8, 2))
        self.status = ttk.Label(frame, text="Scanning hardware (read-only)…", wraplength=410)
        self.status.pack(anchor="w", pady=(5, 12))
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", side="bottom")
        ttk.Button(buttons, text="Open Feather", command=self.open_dashboard).pack(side="left")
        ttk.Button(buttons, text="Connect cloud AI", command=self.connect_cloud).pack(side="left", padx=8)
        ttk.Button(buttons, text="Exit", command=self.close).pack(side="right")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(250, self.open_dashboard)
        self.root.after(250, self.update_status)

    def open_dashboard(self):
        webbrowser.open(f"http://127.0.0.1:{self.http.server_port}/", new=1)

    def update_status(self):
        if self.agent.hardware_ready.is_set():
            report = self.agent.hardware_inventory
            if report.get("status") == "unavailable":
                text = "Feather started, but Windows hardware inventory could not be read. See feather.log."
            else:
                text = "Read-only hardware scan complete. Open Feather to view the report."
            self.status.configure(text=text)
        else:
            self.root.after(500, self.update_status)

    def connect_cloud(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Connect cloud AI")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Use an HTTPS chat-completions-compatible endpoint.",
                  wraplength=380).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        ttk.Label(frame, text="Endpoint").grid(row=1, column=0, sticky="w", pady=4)
        endpoint = ttk.Entry(frame, width=47)
        endpoint.grid(row=1, column=1, pady=4)
        ttk.Label(frame, text="Model").grid(row=2, column=0, sticky="w", pady=4)
        model = ttk.Entry(frame, width=47)
        model.grid(row=2, column=1, pady=4)
        ttk.Label(frame, text="API key").grid(row=3, column=0, sticky="w", pady=4)
        key = ttk.Entry(frame, width=47, show="•")
        key.grid(row=3, column=1, pady=4)
        ttk.Label(frame, text="The key stays in memory for this run and is not saved to disk.",
                  wraplength=380).grid(row=4, column=0, columnspan=2, sticky="w", pady=(7, 10))

        def submit():
            url, model_name, secret = endpoint.get().strip(), model.get().strip(), key.get().strip()
            if urlparse(url).scheme != "https" or not urlparse(url).netloc:
                messagebox.showerror("Invalid endpoint", "Enter a complete HTTPS endpoint.", parent=dialog)
                return
            if not model_name or not secret:
                messagebox.showerror("Missing information", "Enter the model name and API key.", parent=dialog)
                return
            os.environ.update(FEATHER_AI_URL=url, FEATHER_AI_MODEL=model_name, FEATHER_AI_KEY=secret)
            if not self.ai_thread or not self.ai_thread.is_alive():
                self.ai_thread = threading.Thread(target=cloud.worker,
                                                  args=(self.agent, self.stop_event), daemon=True)
                self.ai_thread.start()
            key.delete(0, "end")
            dialog.destroy()
            messagebox.showinfo("Cloud AI connected", "Feather will send a provider request only after you submit a task.",
                                parent=self.root)

        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, columnspan=2, sticky="e")
        ttk.Button(buttons, text="Connect", command=submit).pack(side="left", padx=5)
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="left")
        endpoint.focus_set()

    def close(self):
        if self.stop_event.is_set():
            return
        self.stop_event.set()
        try:
            self.http.shutdown()
            self.http.server_close()
        finally:
            self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    if "--mcp" in sys.argv[1:]:
        # MCP clients use stdio, while the same app-data paths preserve reports
        # and source edits between MCP sessions.
        home = app_data_dir()
        source = home / "source"
        home.mkdir(parents=True, exist_ok=True)
        seed_editable_source(source)
        args = ["--mcp", "--data-dir", str(home / "data"), "--port", "0"]
        sys.argv = [sys.argv[0], *args]
        server_main(default_source_dir=str(source))
        return
    try:
        FeatherPrep().run()
    except Exception as exc:
        logging.exception("Feather Prep could not start")
        try:
            messagebox.showerror("Feather Prep could not start", f"{type(exc).__name__}: {exc}")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
