"""Opt-in, minimal device check-in for the Feather PC list."""
import json
import os
from pathlib import Path
import platform
import secrets
import threading
import urllib.error
import urllib.request

from . import __version__


# The installed app uses the FeatherOS registry; tests and local setups may override it.
REGISTRY_URL = os.environ.get("FEATHER_REGISTRY_URL") or "https://featheros.vercel.app"
REPORT_URL = REGISTRY_URL.rstrip("/") + "/api/report" if REGISTRY_URL else ""
UNREGISTER_URL = REGISTRY_URL.rstrip("/") + "/api/unregister" if REGISTRY_URL else ""
REPORT_INTERVAL_SECONDS = 12 * 60 * 60


def configured():
    return REPORT_URL.startswith("https://") and UNREGISTER_URL.startswith("https://")


def identity_path(data_dir):
    return Path(data_dir) / "device-registry.json"


def get_identity(data_dir, create=True):
    path = identity_path(data_dir)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if (isinstance(value, dict) and len(value.get("id", "")) == 32
                and len(value.get("token", "")) == 64):
            return value
    except (OSError, ValueError, TypeError):
        pass
    if not create:
        return None
    value = {"id": secrets.token_hex(16), "token": secrets.token_hex(32)}
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value), encoding="utf-8")
    os.replace(temp, path)
    return value


def _first_row(value):
    if isinstance(value, list):
        return value[0] if value and isinstance(value[0], dict) else {}
    return value if isinstance(value, dict) else {}


def make_report(identity, hardware):
    computer = _first_row(hardware.get("computer"))
    operating_system = _first_row(hardware.get("operating_system"))
    os_name = operating_system.get("Caption") or platform.system()
    os_version = operating_system.get("Version") or platform.release()
    return {
        "id": identity["id"],
        "token": identity["token"],
        "consent": True,
        "name": platform.node() or "Feather PC",
        "manufacturer": str(computer.get("Manufacturer") or computer.get("manufacturer") or "")[:80],
        "model": str(computer.get("Model") or computer.get("model") or "")[:100],
        "os": str(os_name)[:40],
        "osVersion": str(os_version)[:50],
        "appVersion": __version__,
    }


def _post(url, payload):
    if not configured():
        return "Device list is not configured in this Feather build."
    request = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status in (200, 201):
                return "This PC is on your Feather device list."
            return f"Device list returned status {response.status}."
    except urllib.error.HTTPError as exc:
        return f"Device list returned status {exc.code}."
    except (urllib.error.URLError, TimeoutError, OSError):
        return "Device list is offline; Feather will retry later."


def report_once(data_dir, hardware):
    if not configured():
        return "Device list is not configured in this Feather build."
    identity = get_identity(data_dir)
    return _post(REPORT_URL, make_report(identity, hardware))


def unregister(data_dir):
    identity = get_identity(data_dir, create=False)
    if not identity or not configured():
        return
    _post(UNREGISTER_URL, identity)


def report_loop(agent, data_dir, stop_event, on_status=None):
    """Send an initial opted-in report and refresh the check-in twice daily."""
    while not stop_event.is_set():
        if agent.hardware_ready.wait(timeout=30):
            with agent.hardware_lock:
                hardware = json.loads(json.dumps(agent.hardware_inventory))
        else:
            hardware = {}
        status = report_once(data_dir, hardware)
        if on_status:
            on_status(status)
        if stop_event.wait(REPORT_INTERVAL_SECONDS):
            return
