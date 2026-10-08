"""FOS Code Protocol: portable, hash-checked source-code deltas for Feather devices."""
import difflib
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import PurePosixPath
import secrets
import socket
import tempfile
import time
import uuid


PROTOCOL = "FOSCP/1"
MAX_MESSAGE_BYTES = 2 * 1024 * 1024
MAX_CHANGES = 32
_DEVICE_FILE = "device-id.json"
_BLOCKED_PARTS = {".git", ".env", "__pycache__", "node_modules", "feather-data"}
_HARDWARE_PARTS = {"driver", "drivers", "device", "devices", "hardware", "firmware",
                   "boot", "kernel", "gpu", "graphics"}
_HARDWARE_SUFFIXES = {".inf", ".sys", ".ko", ".rom"}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _text_sha(text):
    return _sha(text.encode("utf-8")) if text is not None else None


def _device_id(data_dir):
    path = data_dir / _DEVICE_FILE
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict) and isinstance(value.get("id"), str) and len(value["id"]) == 32:
            return value["id"]
    except (OSError, ValueError, TypeError):
        pass
    identity = uuid.uuid4().hex
    fd, temp = tempfile.mkstemp(dir=data_dir, prefix=".device-id-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump({"id": identity}, output)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return identity


def _validate_path(path):
    if not isinstance(path, str) or not path or "\\" in path or "\x00" in path:
        raise ValueError("FOSCP paths must be relative POSIX paths")
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or any(part in {"", ".", ".."} for part in parsed.parts):
        raise ValueError("FOSCP path escapes the Feather source tree")
    if any(part.lower() in _BLOCKED_PARTS for part in parsed.parts):
        raise ValueError("FOSCP cannot modify private or generated directories")
    if len(path) > 300:
        raise ValueError("FOSCP path is too long")
    return parsed.as_posix()


def _hardware_specific(path):
    parsed = PurePosixPath(path)
    return any(part.lower() in _HARDWARE_PARTS for part in parsed.parts) or parsed.suffix.lower() in _HARDWARE_SUFFIXES


def _hardware_fingerprint(agent):
    try:
        agent.hardware_ready.wait(timeout=2)
        context = agent.hardware_context()
    except Exception:
        return None
    material = {key: context.get(key) for key in
                ("manufacturer", "model", "operatingSystem", "processors", "graphics", "firmwareMode")}
    if not any(material.values()):
        return None
    return _sha(_canonical(material))


def _line_edits(before, after):
    old_lines = before.splitlines(keepends=True)
    new_lines = after.splitlines(keepends=True)
    edits = []
    for tag, start_old, end_old, start_new, end_new in difflib.SequenceMatcher(
            None, old_lines, new_lines, autojunk=False).get_opcodes():
        if tag != "equal":
            edits.append({"start": start_old, "before": old_lines[start_old:end_old],
                          "insert": new_lines[start_new:end_new]})
    return edits


def _apply_edits(before, edits):
    lines = before.splitlines(keepends=True)
    result = []
    cursor = 0
    for edit in edits:
        start = edit["start"]
        old = edit["before"]
        if start < cursor or start > len(lines) or lines[start:start + len(old)] != old:
            raise ValueError("FOSCP patch context does not match its declared base")
        result.extend(lines[cursor:start])
        result.extend(edit["insert"])
        cursor = start + len(old)
    result.extend(lines[cursor:])
    return "".join(result)


def _message_digest(message):
    local_fields = {"integrity_sha256", "applied_at", "applied_by", "source"}
    unsigned = {key: value for key, value in message.items() if key not in local_fields}
    return _sha(_canonical(unsigned))


def make_message(agent, changes, summary="Feather code update"):
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 240:
        summary = "Feather code update"
    if not isinstance(changes, list) or not 1 <= len(changes) <= MAX_CHANGES:
        raise ValueError("FOSCP updates must contain 1 to 32 code changes")
    normalized = []
    hardware_specific = False
    for item in changes:
        path = _validate_path(item["path"])
        before = item.get("before")
        after = item.get("after")
        if before is not None and not isinstance(before, str):
            raise ValueError("FOSCP source must be UTF-8 text")
        if after is not None and not isinstance(after, str):
            raise ValueError("FOSCP source must be UTF-8 text")
        if before is None and after is None:
            raise ValueError("FOSCP cannot represent an empty change")
        if before is not None and len(before.encode("utf-8")) > MAX_MESSAGE_BYTES:
            raise ValueError("FOSCP source exceeds the 2 MiB limit")
        if after is not None and len(after.encode("utf-8")) > MAX_MESSAGE_BYTES:
            raise ValueError("FOSCP source exceeds the 2 MiB limit")
        hardware_specific = hardware_specific or _hardware_specific(path)
        normalized.append({"path": path, "base_sha256": _text_sha(before),
                           "result_sha256": _text_sha(after), "remove": after is None,
                           "edits": _line_edits(before or "", after or "")})
    scope = "machine" if hardware_specific else "general"
    message = {
        "protocol": PROTOCOL,
        "id": uuid.uuid4().hex,
        "created_at": time.time(),
        "origin": {"device_id": _device_id(agent.data), "owner_role": "Mother"},
        "target": "feather-source",
        "summary": summary.strip(),
        "compatibility": {"scope": scope,
                          "hardware_fingerprint": _hardware_fingerprint(agent) if hardware_specific else None,
                          "tested": False},
        "changes": normalized,
    }
    message["integrity_sha256"] = _message_digest(message)
    return message


def validate_message(message):
    if not isinstance(message, dict) or len(_canonical(message)) > MAX_MESSAGE_BYTES:
        raise ValueError("Invalid or oversized FOSCP message")
    if message.get("protocol") != PROTOCOL or message.get("target") != "feather-source":
        raise ValueError("Unsupported FOSCP message or target")
    if not isinstance(message.get("id"), str) or len(message["id"]) != 32 or any(
            ch not in "0123456789abcdef" for ch in message["id"]):
        raise ValueError("Invalid FOSCP change ID")
    if not secrets.compare_digest(str(message.get("integrity_sha256", "")), _message_digest(message)):
        raise ValueError("FOSCP integrity check failed")
    changes = message.get("changes")
    if not isinstance(changes, list) or not 1 <= len(changes) <= MAX_CHANGES:
        raise ValueError("Invalid FOSCP change list")
    compat = message.get("compatibility")
    if not isinstance(compat, dict) or compat.get("scope") not in {"general", "machine"}:
        raise ValueError("Invalid FOSCP compatibility declaration")
    total = 0
    seen = set()
    for change in changes:
        if not isinstance(change, dict):
            raise ValueError("Invalid FOSCP change")
        path = _validate_path(change.get("path"))
        if path in seen:
            raise ValueError("FOSCP message repeats a source path")
        seen.add(path)
        if _hardware_specific(path) and compat["scope"] != "machine":
            raise ValueError("Hardware and driver paths must declare machine-specific compatibility")
        if not isinstance(change.get("remove"), bool):
            raise ValueError("Invalid FOSCP operation")
        for name in ("base_sha256", "result_sha256"):
            digest = change.get(name)
            if digest is not None and (not isinstance(digest, str) or len(digest) != 64 or
                                       any(ch not in "0123456789abcdef" for ch in digest)):
                raise ValueError("Invalid FOSCP hash")
        if (change["remove"] != (change["result_sha256"] is None) or
                change["base_sha256"] is None and change["remove"]):
            raise ValueError("Invalid FOSCP create, update, or remove operation")
        edits = change.get("edits")
        if not isinstance(edits, list) or len(edits) > 10000:
            raise ValueError("Invalid FOSCP line edits")
        previous_end = 0
        for edit in edits:
            if (not isinstance(edit, dict) or not isinstance(edit.get("start"), int) or
                    edit["start"] < previous_end or not isinstance(edit.get("before"), list) or
                    not isinstance(edit.get("insert"), list) or
                    not all(isinstance(line, str) for line in edit["before"] + edit["insert"])):
                raise ValueError("Invalid FOSCP line edit")
            previous_end = edit["start"] + len(edit["before"])
            total += sum(len(line.encode("utf-8")) for line in edit["before"] + edit["insert"])
            if total > MAX_MESSAGE_BYTES:
                raise ValueError("FOSCP patch exceeds the 2 MiB limit")
    return message


def _validate_result(path, text):
    if text is None:
        return
    suffix = PurePosixPath(path).suffix.lower()
    if suffix == ".py":
        compile(text, path, "exec")
    elif suffix == ".json":
        json.loads(text)


def _record_path(agent, change_id):
    return agent.data / "code-changes" / (change_id + ".json")


def apply_message(agent, message, source="local"):
    message = validate_message(message)
    if _record_path(agent, message["id"]).exists():
        return {"change_id": message["id"], "status": "already_applied", "protocol": PROTOCOL}
    compatibility = message["compatibility"]
    if compatibility["scope"] == "machine":
        expected = compatibility.get("hardware_fingerprint")
        if not expected or not secrets.compare_digest(expected, _hardware_fingerprint(agent) or ""):
            raise ValueError("This code update is hardware-specific and does not match this computer")
    planned, old_values = [], {}
    for change in message["changes"]:
        path = change["path"]
        target = agent.path("source", path)
        if target.is_symlink():
            raise ValueError("FOSCP cannot modify symbolic links")
        try:
            before = target.read_text(encoding="utf-8")
        except FileNotFoundError:
            before = None
        except (OSError, UnicodeError) as exc:
            raise ValueError("FOSCP target must be a readable UTF-8 source file") from exc
        if _text_sha(before) != change["base_sha256"]:
            raise ValueError("FOSCP base does not match this Feather version: " + path)
        after = _apply_edits(before or "", change["edits"])
        if change["remove"]:
            after = None
        if _text_sha(after) != change["result_sha256"]:
            raise ValueError("FOSCP result hash does not match: " + path)
        _validate_result(path, after)
        planned.append((target, after))
        old_values[target] = before
    changed = []
    try:
        for target, after in planned:
            if after is None:
                target.unlink()
            else:
                agent.atomic_text(target, after)
            changed.append(target)
    except Exception:
        for target in reversed(changed):
            before = old_values[target]
            if before is None:
                try:
                    target.unlink()
                except OSError:
                    pass
            else:
                agent.atomic_text(target, before)
        raise
    record = dict(message)
    record["applied_at"] = time.time()
    record["applied_by"] = "Feather AI"
    record["source"] = source[:80]
    record_path = _record_path(agent, message["id"])
    record_path.parent.mkdir(parents=True, exist_ok=True)
    agent.atomic_text(record_path, json.dumps(record, ensure_ascii=False, sort_keys=True))
    return {"change_id": message["id"], "status": "applied", "protocol": PROTOCOL,
            "summary": message["summary"], "files": [item["path"] for item in message["changes"]],
            "compatibility": compatibility["scope"]}


def local_write(agent, path, content, summary="Feather AI code update"):
    return local_batch_write(agent, [{"path": path, "content": content}], summary)


def local_batch_write(agent, changes, summary="Feather AI code update"):
    if not isinstance(changes, list) or not 1 <= len(changes) <= MAX_CHANGES:
        raise ValueError("A FOSCP update must contain 1 to 32 source files")
    prepared, seen = [], set()
    for item in changes:
        if not isinstance(item, dict) or set(item) != {"path", "content"} or not isinstance(item["content"], str):
            raise ValueError("Each FOSCP source change needs a path and UTF-8 content")
        path = _validate_path(item["path"])
        if path in seen:
            raise ValueError("FOSCP update repeats a source path")
        seen.add(path)
        if len(item["content"].encode("utf-8")) > MAX_MESSAGE_BYTES:
            raise ValueError("FOSCP source exceeds the 2 MiB limit")
        target = agent.path("source", path)
        if target.is_symlink():
            raise ValueError("Feather cannot update a symbolic link")
        try:
            before = target.read_text(encoding="utf-8")
        except FileNotFoundError:
            before = None
        except (OSError, UnicodeError) as exc:
            raise ValueError("Feather source updates require UTF-8 text files") from exc
        if before != item["content"]:
            prepared.append({"path": path, "before": before, "after": item["content"]})
    if not prepared:
        return {"root": "source", "status": "unchanged", "protocol": PROTOCOL}
    message = make_message(agent, prepared, summary)
    result = apply_message(agent, message, source="local-ai")
    result["restart_may_be_required"] = True
    return result


def history(agent, limit=50):
    records = []
    folder = agent.data / "code-changes"
    if not folder.exists():
        return records
    for path in sorted(folder.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            records.append({"id": value.get("id"), "created_at": value.get("created_at"),
                            "applied_at": value.get("applied_at"), "applied_by": value.get("applied_by"),
                            "source": value.get("source"), "summary": value.get("summary"),
                            "origin": value.get("origin"), "compatibility": value.get("compatibility"),
                            "files": [change.get("path") for change in value.get("changes", [])],
                            "integrity_sha256": value.get("integrity_sha256")})
        except (OSError, ValueError, TypeError):
            continue
    return records


def get_message(agent, change_id):
    if not isinstance(change_id, str) or len(change_id) != 32 or any(ch not in "0123456789abcdef" for ch in change_id):
        raise ValueError("Invalid FOSCP change ID")
    try:
        message = json.loads(_record_path(agent, change_id).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("FOSCP change was not found") from exc
    return validate_message(message)


def preview_message(message):
    message = validate_message(message)
    output = ["FOSCP/1 · " + message["summary"],
              "Owner role: " + str(message.get("origin", {}).get("owner_role", "unknown")),
              "Compatibility: " + message["compatibility"]["scope"], ""]
    for change in message["changes"]:
        output.append("File: " + change["path"])
        output.append("Base SHA-256: " + str(change["base_sha256"]))
        output.append("Result SHA-256: " + str(change["result_sha256"]))
        for edit in change["edits"]:
            output.append("@@ line " + str(edit["start"] + 1) + " @@")
            output.extend("-" + line.rstrip("\r\n") for line in edit["before"])
            output.extend("+" + line.rstrip("\r\n") for line in edit["insert"])
        if change["remove"]:
            output.append("[file removed]")
        output.append("")
    return "\n".join(output)


def rollback(agent, change_id):
    if not isinstance(change_id, str) or len(change_id) != 32 or any(ch not in "0123456789abcdef" for ch in change_id):
        raise ValueError("Invalid FOSCP change ID")
    try:
        previous = json.loads(_record_path(agent, change_id).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("FOSCP change was not found") from exc
    reverse = []
    for change in previous["changes"]:
        current = agent.path("source", change["path"])
        try:
            before = current.read_text(encoding="utf-8")
        except FileNotFoundError:
            before = None
        if _text_sha(before) != change["result_sha256"]:
            raise ValueError("Cannot roll back: this file has newer changes: " + change["path"])
        after = _apply_edits(before or "", change["edits"])
        if change["base_sha256"] is None:
            after = None
        reverse.append({"path": change["path"], "before": before, "after": after})
    message = make_message(agent, reverse, "Rollback: " + previous.get("summary", "Feather code update"))
    result = apply_message(agent, message, source="owner-rollback")
    return result


def _lan_addresses():
    addresses = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM):
            address = info[4][0]
            parsed = ipaddress.ip_address(address)
            if parsed.is_private and not parsed.is_loopback and not parsed.is_link_local:
                addresses.add(address)
    except OSError:
        pass
    if not addresses:
        probe = None
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.connect(("192.0.2.1", 9))
            address = probe.getsockname()[0]
            parsed = ipaddress.ip_address(address)
            if parsed.is_private and not parsed.is_loopback and not parsed.is_link_local:
                addresses.add(address)
        except OSError:
            pass
        finally:
            if probe:
                probe.close()
    return sorted(addresses)


def validate_peer_url(url):
    from urllib.parse import urlparse
    parsed = urlparse(str(url or ""))
    if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("FOSCP peer URL must be an HTTP address on your private network")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise ValueError("Use the peer's private IP address") from exc
    if not address.is_private and not address.is_loopback:
        raise ValueError("FOSCP only connects directly to private-network peers")
    if not parsed.port or parsed.path not in {"", "/", "/foscp/v1/receive"}:
        raise ValueError("Enter a peer address with a port")
    return "http://" + parsed.netloc + "/foscp/v1/receive"


def peer_auth_header(token, payload):
    return "FOSCP-HMAC " + hmac.new(token.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def verify_peer_auth(token, payload, header):
    return secrets.compare_digest(str(header or ""), peer_auth_header(token, payload))


def send_message(url, token, message):
    import urllib.error
    import urllib.request

    endpoint = validate_peer_url(url)
    if not isinstance(token, str) or len(token) < 32 or len(token) > 128:
        raise ValueError("Enter the peer's temporary pairing key")
    payload = _canonical(validate_message(message))
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, response, code, message, headers, new_url):
            raise ValueError("FOSCP peers cannot redirect code updates")

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(endpoint, data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "Authorization": peer_auth_header(token, payload)}, method="POST")
    try:
        with opener.open(request, timeout=15) as response:
            data = response.read(16385)
            if len(data) > 16384:
                raise ValueError("Peer response exceeds the FOSCP limit")
            return json.loads(data)
    except urllib.error.HTTPError as exc:
        detail = exc.read(4096).decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("error", "Peer rejected the code update")
        except (ValueError, AttributeError):
            detail = "Peer rejected the code update"
        raise ValueError(detail) from exc
