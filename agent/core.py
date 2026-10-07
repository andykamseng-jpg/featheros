import hashlib
import json
from datetime import datetime, timezone
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import zipfile

from .resources import resource_profile


WINDOWS_INVENTORY_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
function Read-Class($class, $fields) {
  try {
    if (Get-Command Get-CimInstance -ErrorAction SilentlyContinue) {
      $items = Get-CimInstance -ClassName $class -ErrorAction Stop
    } else {
      $items = Get-WmiObject -Class $class -ErrorAction Stop
    }
    $rows = @()
    foreach ($item in $items) {
      $row = [ordered]@{}
      foreach ($field in $fields) { $row[$field] = $item.$field }
      $rows += [pscustomobject]$row
    }
    return $rows
  } catch { return }
}
$firmwareCode = (Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control' -Name PEFirmwareType -ErrorAction SilentlyContinue).PEFirmwareType
$firmware = switch ($firmwareCode) { 1 { 'BIOS' } 2 { 'UEFI' } default { 'unknown' } }
$secureBoot = $null
try { $secureBoot = Confirm-SecureBootUEFI -ErrorAction Stop } catch { }
$drivers = @(Read-Class 'Win32_PnPSignedDriver' @('DeviceName','DriverVersion','DriverProviderName','IsSigned'))
if ($drivers.Count -gt 200) { $drivers = @($drivers | Select-Object -First 200) }
$report = [ordered]@{
  collection_mode = 'read_only'
  operating_system = @(Read-Class 'Win32_OperatingSystem' @('Caption','Version','BuildNumber','OSArchitecture','FreePhysicalMemory'))
  computer = @(Read-Class 'Win32_ComputerSystem' @('Manufacturer','Model','SystemType','TotalPhysicalMemory'))
  processors = @(Read-Class 'Win32_Processor' @('Name','AddressWidth','DataWidth','NumberOfCores','NumberOfLogicalProcessors'))
  firmware_mode = $firmware
  secure_boot = $secureBoot
  bios = @(Read-Class 'Win32_BIOS' @('Manufacturer','SMBIOSBIOSVersion','ReleaseDate'))
  boards = @(Read-Class 'Win32_BaseBoard' @('Manufacturer','Product','Version'))
  memory_modules = @(Read-Class 'Win32_PhysicalMemory' @('Capacity','Speed','Manufacturer','PartNumber'))
  disks = @(Read-Class 'Win32_DiskDrive' @('Model','InterfaceType','MediaType','Size'))
  volumes = @(Read-Class 'Win32_LogicalDisk' @('DeviceID','FileSystem','Size','FreeSpace'))
  graphics = @(Read-Class 'Win32_VideoController' @('Name','DriverVersion','PNPDeviceID','AdapterRAM'))
  network_hardware = @(Read-Class 'Win32_NetworkAdapter' @('Name','Manufacturer','PNPDeviceID','NetEnabled'))
  installed_drivers = $drivers
}
ConvertTo-Json -InputObject $report -Depth 6 -Compress
"""


def windows_hardware_inventory():
    """Collect a bounded, read-only Windows hardware summary through WMI."""
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", WINDOWS_INVENTORY_SCRIPT],
            capture_output=True, text=True, timeout=25, check=True,
        )
        result = json.loads(proc.stdout)
        if not isinstance(result, dict):
            raise ValueError("Windows inventory returned an invalid report")
        return result
    except Exception as exc:
        return {"collection_mode": "read_only", "status": "unavailable",
                "reason": type(exc).__name__}


def linux_hardware_inventory():
    """Read basic machine identifiers from Linux kernel sysfs/procfs."""
    def read(path):
        try:
            return Path(path).read_text(errors="replace").strip() or None
        except OSError:
            return None

    cpu = None
    for line in Path("/proc/cpuinfo").read_text(errors="replace").splitlines() if Path("/proc/cpuinfo").exists() else []:
        if line.lower().startswith(("model name", "hardware")):
            cpu = line.split(":", 1)[-1].strip()
            break
    memory = read("/proc/meminfo")
    memory_kib = None
    if memory:
        for line in memory.splitlines():
            if line.startswith("MemTotal:"):
                try:
                    memory_kib = int(line.split()[1])
                except (ValueError, IndexError):
                    pass
                break
    disks = []
    for device in sorted(Path("/sys/block").glob("*")):
        if device.name.startswith(("loop", "ram", "zram")):
            continue
        sectors = read(device / "size")
        try:
            size_bytes = int(sectors) * 512 if sectors else None
        except ValueError:
            size_bytes = None
        disks.append({"device": device.name, "model": read(device / "device/model"),
                      "size_bytes": size_bytes})
    networks = []
    for device in sorted(Path("/sys/class/net").glob("*")):
        if device.name == "lo":
            continue
        try:
            driver = (device / "device/driver").resolve().name
        except OSError:
            driver = None
        networks.append({"device": device.name, "driver": driver})
    return {
        "collection_mode": "read_only",
        "manufacturer": read("/sys/class/dmi/id/sys_vendor"),
        "model": read("/sys/class/dmi/id/product_name"),
        "motherboard": read("/sys/class/dmi/id/board_name"),
        "firmware_version": read("/sys/class/dmi/id/bios_version"),
        "processor": cpu,
        "memory_total_kib": memory_kib,
        "disks": disks,
        "network_hardware": networks,
    }


def spec(name, description, properties, required=()):
    return {"name": name, "description": description, "inputSchema": {
        "type": "object", "properties": properties, "required": list(required),
        "additionalProperties": False}}


STRING = {"type": "string"}
TOOLS = [
    spec("system_info", "Automatically inspect Feather host and read-only hardware inventory", {}),
    spec("file_list", "List files under a writable root", {"root": STRING, "path": STRING}),
    spec("file_read", "Read a UTF-8 source or project file", {"root": STRING, "path": STRING}, ("path",)),
    spec("file_write", "Create or edit a UTF-8 source or project file atomically", {"root": STRING, "path": STRING, "content": STRING}, ("path", "content")),
    spec("revision_save", "Save a named code/workspace revision on the hard disk", {"root": STRING, "label": STRING}),
    spec("revision_list", "List saved revisions", {}),
    spec("revision_restore", "Restore saved files; extra newer files are retained; restart modified services separately", {"revision": STRING}, ("revision",)),
    spec("command_run", "Run a command as the current user when enabled by launch option", {"argv": {"type": "array", "items": STRING, "minItems": 1}, "root": STRING}, ("argv",)),
    spec("task_next", "Claim the next typed/spoken task from the Feather dashboard", {}),
    spec("task_reply", "Complete a claimed task with a response shown and spoken by the dashboard", {"id": STRING, "text": STRING}, ("id", "text")),
]


class Agent:
    def __init__(self, data_dir, source_dir, enable_commands=False):
        self.data = Path(data_dir).resolve()
        self.data.mkdir(parents=True, exist_ok=True)
        self.workspace = self.data / "workspace"
        self.workspace.mkdir(exist_ok=True)
        self.roots = {"workspace": self.workspace.resolve(), "source": Path(source_dir).resolve()}
        self.revisions = self.data / "revisions"
        self.revisions.mkdir(exist_ok=True)
        self.enable_commands = enable_commands
        self.mcp_connected = False
        self.lock = threading.RLock()
        self.hardware_lock = threading.Lock()
        self.hardware_profile_path = self.data / "hardware-profile.json"
        self.hardware_profile = self._load_hardware_profile()
        self.hardware_inventory = {"collection_mode": "read_only", "status": "scanning"}
        self.hardware_ready = threading.Event()
        threading.Thread(target=self._scan_local_hardware, name="feather-hardware-scan", daemon=True).start()
        self.task_file = self.data / "tasks.json"
        self.tasks = json.loads(self.task_file.read_text()) if self.task_file.exists() else []
        # A interrupted provider/MCP session can be retried explicitly after restart.
        for t in self.tasks:
            if t["state"] == "working":
                t["state"] = "interrupted"

    def _scan_local_hardware(self):
        """Start the read-only inventory automatically when Feather launches."""
        try:
            system = platform.system()
            if system == "Windows":
                inventory = windows_hardware_inventory()
            elif system == "Linux":
                inventory = linux_hardware_inventory()
            else:
                inventory = {"collection_mode": "read_only", "status": "unsupported_platform"}
        except Exception as exc:
            inventory = {"collection_mode": "read_only", "status": "unavailable",
                          "reason": type(exc).__name__}
        with self.hardware_lock:
            self.hardware_inventory = inventory
            if inventory.get("status") not in {"unavailable", "scanning", "unsupported_platform"}:
                profile = {"scanned_at": datetime.now(timezone.utc).isoformat(), "hardware": inventory}
                try:
                    self._write_hardware_profile(profile)
                    self.hardware_profile = profile
                except OSError:
                    pass
            self.hardware_ready.set()

    def _load_hardware_profile(self):
        try:
            if self.hardware_profile_path.stat().st_size > 2 * 1024 * 1024:
                return None
            value = json.loads(self.hardware_profile_path.read_text(encoding="utf-8"))
            if isinstance(value, dict) and isinstance(value.get("hardware"), dict):
                return value
        except (OSError, ValueError, TypeError):
            pass
        return None

    def _write_hardware_profile(self, profile):
        fd, temp = tempfile.mkstemp(dir=self.data, prefix=".hardware-profile-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(profile, output, ensure_ascii=False, separators=(",", ":"))
            os.replace(temp, self.hardware_profile_path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def hardware_context(self):
        """Return a compact, persistent summary for the local AI's system prompt."""
        with self.hardware_lock:
            profile = self.hardware_profile
            current = self.hardware_inventory
            if profile:
                source = profile.get("hardware", {})
                scanned_at = profile.get("scanned_at")
            else:
                source = current
                scanned_at = None
            snapshot = json.loads(json.dumps(source))
        def first(value):
            if isinstance(value, dict):
                return value
            return value[0] if isinstance(value, list) and value and isinstance(value[0], dict) else {}
        computer = first(snapshot.get("computer"))
        os_info = first(snapshot.get("operating_system"))
        processors = snapshot.get("processors") if isinstance(snapshot.get("processors"), list) else []
        graphics = snapshot.get("graphics") if isinstance(snapshot.get("graphics"), list) else []
        disks = snapshot.get("disks") if isinstance(snapshot.get("disks"), list) else []
        drivers = snapshot.get("installed_drivers") if isinstance(snapshot.get("installed_drivers"), list) else []
        return {
            "scanSavedAt": scanned_at,
            "scanStatus": current.get("status", "complete"),
            "manufacturer": computer.get("Manufacturer") or snapshot.get("manufacturer"),
            "model": computer.get("Model") or snapshot.get("model"),
            "operatingSystem": os_info.get("Caption"),
            "processors": [{"name": row.get("Name"), "cores": row.get("NumberOfCores"),
                            "logicalProcessors": row.get("NumberOfLogicalProcessors")}
                           for row in processors[:4] if isinstance(row, dict)],
            "totalMemoryBytes": computer.get("TotalPhysicalMemory"),
            "memoryTotalKiB": snapshot.get("memory_total_kib"),
            "memoryAvailableKiB": os_info.get("FreePhysicalMemory"),
            "graphics": [{"name": row.get("Name"), "driverVersion": row.get("DriverVersion")}
                         for row in graphics[:8] if isinstance(row, dict)],
            "storage": [{"model": row.get("Model") or row.get("model"),
                         "sizeBytes": row.get("Size") or row.get("size_bytes")}
                        for row in disks[:8] if isinstance(row, dict)],
            "installedDrivers": [{"name": row.get("DeviceName"), "provider": row.get("DriverProviderName"),
                                  "version": row.get("DriverVersion")}
                                 for row in drivers[:24] if isinstance(row, dict)],
            "firmwareMode": snapshot.get("firmware_mode"),
        }

    def path(self, root="workspace", name="."):
        if root not in self.roots:
            raise ValueError("Unknown root")
        base = self.roots[root]
        p = (base / name).resolve()
        if not p.is_relative_to(base):
            raise ValueError("Path must remain inside the selected root")
        # Agent state and revision storage are not source/project editing targets.
        if p.is_relative_to(self.data) and not p.is_relative_to(self.workspace):
            raise ValueError("Agent state is not a writable source target")
        return p

    def atomic_text(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".feather-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def audit(self, name, success):
        # Keep tool names/status, never model keys or file contents.
        with self.lock:
            with (self.data / "activity.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"time": time.time(), "tool": name, "success": success}) + "\n")

    def call(self, name, args):
        definition = next((t for t in TOOLS if t["name"] == name), None)
        if not definition:
            raise ValueError("Unknown tool")
        schema = definition["inputSchema"]
        if not isinstance(args, dict) or set(args) - set(schema["properties"]):
            raise ValueError("Unexpected tool arguments")
        if any(key not in args for key in schema["required"]):
            raise ValueError("Missing tool argument")
        for key, value in args.items():
            kind = schema["properties"][key]["type"]
            if kind == "string" and not isinstance(value, str):
                raise ValueError("Expected a string")
            if kind == "array" and (not isinstance(value, list) or not value or
                                     not all(isinstance(v, str) and v for v in value)):
                raise ValueError("Expected nonempty command arguments")
        try:
            with self.lock:
                result = self._call(name, args)
            self.audit(name, True)
            return result
        except Exception:
            self.audit(name, False)
            raise

    def _call(self, name, a):
        root = a.get("root", "workspace")
        if name == "system_info":
            usage = shutil.disk_usage(self.data)
            self.hardware_ready.wait(timeout=5)
            with self.hardware_lock:
                hardware = json.loads(json.dumps(self.hardware_inventory))
                profile = self.hardware_profile
            if hardware.get("status") in {"scanning", "unavailable"} and profile:
                hardware = json.loads(json.dumps(profile["hardware"]))
            return {"os": platform.system(), "release": platform.release(),
                    "architecture": platform.machine(), "disk_free_bytes": usage.free,
                    "hardware": hardware,
                    "resource_profile": resource_profile(hardware),
                    "hardware_profile_saved_at": profile.get("scanned_at") if profile else None,
                    "hardware_profile_file": str(self.hardware_profile_path) if profile else None,
                    "roots": {k: str(v) for k, v in self.roots.items()},
                    "commands_enabled": self.enable_commands}
        if name == "file_list":
            p = self.path(root, a.get("path", "."))
            return [{"name": x.name, "directory": x.is_dir()} for x in sorted(p.iterdir())][:500]
        if name == "file_read":
            p = self.path(root, a["path"])
            if p.stat().st_size > 2 * 1024 * 1024:
                raise ValueError("Read limit is 2 MiB")
            return {"content": p.read_text(encoding="utf-8")}
        if name == "file_write":
            if len(a["content"].encode()) > 2 * 1024 * 1024:
                raise ValueError("Write limit is 2 MiB")
            p = self.path(root, a["path"])
            if p == self.roots[root]:
                raise ValueError("Choose a file")
            self.atomic_text(p, a["content"])
            return {"saved": a["path"], "root": root, "restart_may_be_required": root == "source"}
        if name == "revision_save":
            if root not in self.roots:
                raise ValueError("Unknown root")
            rev = uuid.uuid4().hex
            total, files = 0, []
            for p in self.roots[root].rglob("*"):
                rel = p.relative_to(self.roots[root])
                if any(part in {".git", "__pycache__", "node_modules", ".env", "feather-data"}
                       for part in rel.parts):
                    continue
                if p.is_symlink() or not p.is_file():
                    continue
                if p.resolve().is_relative_to(self.data) and root != "workspace":
                    continue
                total += p.stat().st_size
                files.append((p, rel))
                if total > 512 * 1024 * 1024 or len(files) > 2000:
                    raise ValueError("Revision limit: 512 MiB / 2000 files")
            with zipfile.ZipFile(self.revisions / (rev + ".zip"), "w", zipfile.ZIP_DEFLATED) as z:
                for p, rel in files:
                    z.write(p, rel.as_posix())
            meta = {"id": rev, "root": root, "label": a.get("label", ""),
                    "time": time.time(), "files": len(files), "bytes": total}
            self.atomic_text(self.revisions / (rev + ".json"), json.dumps(meta))
            return meta
        if name == "revision_list":
            return [json.loads(p.read_text()) for p in sorted(self.revisions.glob("*.json"))]
        if name == "revision_restore":
            rev = a["revision"]
            if len(rev) != 32 or any(c not in "0123456789abcdef" for c in rev):
                raise ValueError("Invalid revision ID")
            meta = json.loads((self.revisions / (rev + ".json")).read_text())
            with zipfile.ZipFile(self.revisions / (rev + ".zip")) as z:
                planned = [(self.path(meta["root"], n), n) for n in z.namelist()]
                for p, n in planned:
                    if z.getinfo(n).file_size > 2 * 1024 * 1024:
                        raise ValueError("Restore file exceeds 2 MiB limit")
                for p, n in planned:
                    # Revisions can include binaries; preserve the exact bytes.
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(z.read(n))
            return {"restored": rev, "extra_new_files_retained": True}
        if name == "command_run":
            if not self.enable_commands:
                raise ValueError("Commands require --enable-commands at launch")
            p = self.path(root)
            # No shell interpolation. The current user defines the authority boundary.
            log = tempfile.TemporaryFile()
            try:
                proc = subprocess.Popen(a["argv"], cwd=p, stdout=log, stderr=subprocess.STDOUT)
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    raise ValueError("Command exceeded 30 seconds; descendant processes may need separate cleanup")
                log.seek(0)
                out = log.read(128 * 1024)
                return {"exit_code": proc.returncode, "output": out.decode("utf-8", "replace")}
            finally:
                log.close()
        if name == "task_next":
            for t in self.tasks:
                if t["state"] == "queued":
                    t["state"] = "working"
                    self.save_tasks()
                    return dict(t)
            return {"task": None}
        if name == "task_reply":
            t = next((t for t in self.tasks if t["id"] == a["id"]), None)
            if not t or t["state"] != "working":
                raise ValueError("Task must have been claimed")
            t.update(state="done", reply=a["text"][:20000])
            self.save_tasks()
            return {"completed": t["id"]}

    def save_tasks(self):
        self.atomic_text(self.task_file, json.dumps(self.tasks, ensure_ascii=False))

    def submit(self, text):
        if not isinstance(text, str) or not text.strip() or len(text) > 10000:
            raise ValueError("Enter a task of up to 10000 characters")
        with self.lock:
            if sum(t["state"] in {"queued", "working"} for t in self.tasks) >= 20:
                raise ValueError("Task queue is full")
            self.tasks = self.tasks[-99:]
            t = {"id": uuid.uuid4().hex, "text": text, "state": "queued", "time": time.time()}
            self.tasks.append(t)
            self.save_tasks()
            return dict(t)
