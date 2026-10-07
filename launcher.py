"""Feather Prep desktop launcher; its hardware inventory is read-only."""
import logging
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk
import webbrowser

from agent import local_ai
from agent import runtime
from agent.core import Agent
from agent import registry
from agent import updater
from agent.server import make_http, main as server_main


APP_NAME = "FeatherOS"


def app_data_dir():
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / APP_NAME


def _update_once():
    if os.name != "nt" or os.environ.get("FEATHER_AUTO_UPDATE") == "0":
        return
    home = app_data_dir()
    home.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=home / "feather.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    try:
        release = updater.fetch_latest()
        if not release:
            return
        installer = updater.stage_release(home, release)
        subprocess.Popen([str(installer), "/SILENT", "/NORESTART", "/CLOSEAPPLICATIONS",
                          "/FORCECLOSEAPPLICATIONS", "/NORESTARTAPPLICATIONS"],
                         close_fds=True, cwd=str(home))
    except Exception:
        logging.exception("Scheduled automatic update check failed")


def _remove_update_task():
    """Remove the legacy 30-minute task installed by earlier Feather Prep builds."""
    if os.name != "nt":
        return
    home = app_data_dir()
    home.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=home / "feather.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    try:
        result = subprocess.run(
            ["schtasks.exe", "/Delete", "/TN", "FeatherOS Auto Update", "/F"],
            capture_output=True, text=True, timeout=30, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            logging.info("Legacy update task was not present or could not be removed: %s",
                         (result.stderr or result.stdout).strip())
    except (OSError, subprocess.SubprocessError):
        logging.exception("Could not remove legacy per-user update task")


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

        self.settings_file = self.home / "settings.json"
        try:
            settings = json.loads(self.settings_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            settings = {}
        if not isinstance(settings, dict):
            settings = {}
        saved_local = local_ai.validate_configuration(
            settings.get("local_ai_url"), settings.get("local_ai_model"))
        if saved_local:
            os.environ.update(FEATHER_LOCAL_AI_URL=saved_local["endpoint"],
                              FEATHER_LOCAL_AI_MODEL=saved_local["model"],
                              FEATHER_AI_MODE="local")

        logging.basicConfig(filename=self.home / "feather.log", level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(message)s")
        self.agent = Agent(self.data_dir, self.source_dir)
        self.http = make_http(self.agent)
        self.stop_event = threading.Event()
        self.registry_stop = threading.Event()
        self.registry_thread = None
        self.update_pending = False
        self.http_thread = threading.Thread(target=self.http.serve_forever,
                                            name="feather-local-dashboard", daemon=True)
        self.http_thread.start()
        self.ai_thread = None
        if runtime.configured():
            self.ai_thread = threading.Thread(target=runtime.worker,
                                              args=(self.agent, self.stop_event), daemon=True)
            self.ai_thread.start()

        self.root = tk.Tk()
        self.root.title("Feather Prep")
        self.root.geometry("680x460")
        self.root.resizable(True, True)
        self.root.minsize(620, 420)
        frame = ttk.Frame(self.root, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Feather Prep", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Feather is checking this PC before an installation decision. Windows is untouched.",
                  wraplength=410).pack(anchor="w", pady=(8, 2))
        self.status = ttk.Label(frame, text="Scanning hardware (read-only)…", wraplength=410)
        self.status.pack(anchor="w", pady=(5, 12))
        self.share_device = tk.BooleanVar(value=settings.get("share_device") is not False)
        ttk.Checkbutton(frame, text="Send hardware report to my Feather registry",
                        variable=self.share_device, command=self.toggle_device_sharing).pack(anchor="w")
        self.registry_status = ttk.Label(frame, text="Waiting for hardware scan…", wraplength=450)
        self.registry_status.pack(anchor="w", pady=(4, 10))
        self.update_status_label = ttk.Label(frame, text="Checking for Feather updates…" if os.name == "nt" else "", wraplength=450)
        self.update_status_label.pack(anchor="w", pady=(0, 5))
        ttk.Label(frame, text="Sends PC name, model, firmware version, device IDs and installed driver names/versions; no files or serial numbers.",
                  wraplength=450).pack(anchor="w")
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", side="bottom")
        ttk.Button(buttons, text="Open Feather AI", command=self.open_dashboard).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Local AI", command=self.connect_local_ai).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Online AI", command=self.connect_cloud).pack(side="left")
        ttk.Button(buttons, text="Exit", command=self.close).pack(side="right")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(250, self.update_status)
        if self.share_device.get():
            self.start_device_reporting()
        if os.name == "nt" and os.environ.get("FEATHER_AUTO_UPDATE") != "0":
            threading.Thread(target=self.check_updates, name="feather-auto-update", daemon=True).start()

    def check_updates(self):
        """Check once at startup and install only a verified official release."""
        if self.stop_event.is_set():
            return
        try:
            release = updater.fetch_latest()
            if not release:
                self.show_update_status("Feather Prep is up to date.")
                return
            self.show_update_status("Downloading verified " + release["tag"] + " update…")
            installer = updater.stage_release(self.home, release)
            self.root.after(0, lambda: self.install_update(installer, release["tag"]))
        except Exception:
            logging.exception("Automatic update check failed")
            self.show_update_status("Update check failed; try again next time Feather Prep starts.")

    def show_update_status(self, value):
        try:
            self.root.after(0, lambda: self.update_status_label.configure(text=value))
        except tk.TclError:
            pass

    def install_update(self, installer, tag):
        if self.stop_event.is_set() or self.update_pending:
            return
        self.update_pending = True
        self.update_status_label.configure(text="Installing verified " + tag + "; Feather will restart.")
        try:
            subprocess.Popen([str(installer), "/SILENT", "/NORESTART", "/CLOSEAPPLICATIONS",
                              "/FORCECLOSEAPPLICATIONS", "/NORESTARTAPPLICATIONS"],
                             close_fds=True)
        except OSError:
            logging.exception("Could not start verified Feather installer")
            self.update_pending = False
            self.update_status_label.configure(text="Update could not start; retry on next launch.")
            return
        self.close()

    def save_device_preference(self):
        try:
            try:
                settings = json.loads(self.settings_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                settings = {}
            if not isinstance(settings, dict):
                settings = {}
            settings["share_device"] = self.share_device.get()
            temp = self.settings_file.with_suffix(".tmp")
            temp.write_text(json.dumps(settings), encoding="utf-8")
            os.replace(temp, self.settings_file)
        except OSError:
            logging.exception("Could not save device-list preference")

    def toggle_device_sharing(self):
        self.save_device_preference()
        if self.share_device.get():
            self.start_device_reporting()
        else:
            self.registry_stop.set()
            self.registry_status.configure(text="Sharing is off. Removing this PC from your list…")
            threading.Thread(target=registry.unregister, args=(self.data_dir,), daemon=True).start()

    def start_device_reporting(self):
        if not registry.configured():
            self.registry_status.configure(text="Sharing is enabled, but the device list is not configured in this build yet.")
            return
        if self.registry_thread and self.registry_thread.is_alive():
            return
        self.registry_stop = threading.Event()

        def update_status(text):
            try:
                self.root.after(0, lambda: self.registry_status.configure(text=text))
            except tk.TclError:
                pass

        self.registry_thread = threading.Thread(
            target=registry.report_loop,
            args=(self.agent, self.data_dir, self.registry_stop, update_status),
            name="feather-device-registry", daemon=True,
        )
        self.registry_thread.start()

    def open_dashboard(self):
        webbrowser.open(f"http://127.0.0.1:{self.http.server_port}/", new=1)

    def update_status(self):
        if self.agent.hardware_ready.is_set():
            report = self.agent.hardware_inventory
            if report.get("status") == "unavailable":
                text = "Feather started, but Windows hardware inventory could not be read. See feather.log."
            else:
                text = "Hardware scan complete. Replacement is blocked until a bootable FeatherOS image and matching drivers exist."
            self.status.configure(text=text)
        else:
            self.root.after(500, self.update_status)

    def connect_local_ai(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Connect local AI")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Connect a model server running on this PC. Feather keeps local prompts on this computer.",
                  wraplength=420).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        ttk.Label(frame, text="Local endpoint").grid(row=1, column=0, sticky="w", pady=4)
        endpoint = ttk.Entry(frame, width=48)
        endpoint.insert(0, os.environ.get("FEATHER_LOCAL_AI_URL", "http://127.0.0.1:1234/v1/chat/completions"))
        endpoint.grid(row=1, column=1, pady=4)
        ttk.Label(frame, text="Model name").grid(row=2, column=0, sticky="w", pady=4)
        model = ttk.Entry(frame, width=48)
        model.insert(0, os.environ.get("FEATHER_LOCAL_AI_MODEL", ""))
        model.grid(row=2, column=1, pady=4)
        ttk.Label(frame, text="This build connects to an existing OpenAI-compatible local model server; it does not download a model.",
                  wraplength=420).grid(row=3, column=0, columnspan=2, sticky="w", pady=(7, 10))

        def submit():
            config = local_ai.validate_configuration(endpoint.get(), model.get())
            if not config:
                messagebox.showerror("Invalid local AI", "Use a local loopback endpoint and enter the model name.", parent=dialog)
                return
            os.environ.update(FEATHER_LOCAL_AI_URL=config["endpoint"],
                              FEATHER_LOCAL_AI_MODEL=config["model"], FEATHER_AI_MODE="local")
            try:
                settings = json.loads(self.settings_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                settings = {}
            settings.update(local_ai_url=config["endpoint"], local_ai_model=config["model"])
            temp = self.settings_file.with_suffix(".tmp")
            temp.write_text(json.dumps(settings), encoding="utf-8")
            os.replace(temp, self.settings_file)
            if not self.ai_thread or not self.ai_thread.is_alive():
                self.ai_thread = threading.Thread(target=runtime.worker,
                                                  args=(self.agent, self.stop_event), daemon=True)
                self.ai_thread.start()
            dialog.destroy()
            messagebox.showinfo("Local AI selected", "Feather will use this local endpoint for new tasks.", parent=self.root)

        buttons = ttk.Frame(frame)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e")
        ttk.Button(buttons, text="Connect", command=submit).pack(side="left", padx=5)
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="left")
        endpoint.focus_set()

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
            os.environ.update(FEATHER_AI_URL=url, FEATHER_AI_MODEL=model_name,
                              FEATHER_AI_KEY=secret, FEATHER_AI_MODE="online")
            if not self.ai_thread or not self.ai_thread.is_alive():
                self.ai_thread = threading.Thread(target=runtime.worker,
                                                  args=(self.agent, self.stop_event), daemon=True)
                self.ai_thread.start()
            key.delete(0, "end")
            dialog.destroy()
            messagebox.showinfo("Online AI selected", "Feather will send a provider request only after you submit a task.",
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
        self.registry_stop.set()
        try:
            self.http.shutdown()
            self.http.server_close()
        finally:
            self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    if "--update-once" in sys.argv[1:]:
        _update_once()
        return
    if "--remove-update-task" in sys.argv[1:]:
        _remove_update_task()
        return
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

