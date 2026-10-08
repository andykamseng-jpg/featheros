"""Low-rate FOSCP message relay for Feather peers on separate networks."""
import json
import os
import time
import urllib.error
import urllib.request

from . import code_sync, registry


POLL_SECONDS = 300
MAX_PULL = 2
MAX_PUBLISHED_IDS = 2000
STATE_FILE = "f2f-relay-state.json"
MAX_RESPONSE_BYTES = code_sync.MAX_MESSAGE_BYTES * MAX_PULL + 64 * 1024


def relay_base_url():
    return (os.environ.get("FEATHER_F2F_URL") or registry.REGISTRY_URL or "").rstrip("/")


def configured():
    return relay_base_url().startswith("https://")


def _endpoint(action):
    return relay_base_url() + "/api/f2f/" + action


def _post(action, payload):
    url = _endpoint(action)
    if not url.startswith("https://"):
        raise ValueError("F2F internet relay requires an HTTPS registry URL")

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, response, code, message, headers, new_url):
            raise ValueError("F2F relay requests cannot redirect")

    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > code_sync.MAX_MESSAGE_BYTES + 64 * 1024:
        raise ValueError("FOSCP relay request exceeds its size limit")
    request = urllib.request.Request(url, data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=20) as response:
            data = response.read(MAX_RESPONSE_BYTES + 1)
            if len(data) > MAX_RESPONSE_BYTES:
                raise ValueError("FOSCP relay response exceeds its size limit")
            result = json.loads(data)
            if not isinstance(result, dict):
                raise ValueError("FOSCP relay returned an invalid response")
            return result
    except urllib.error.HTTPError as exc:
        try:
            error = json.loads(exc.read(4096).decode("utf-8", "replace")).get("error")
        except (ValueError, AttributeError):
            error = None
        raise ValueError(error or "FOSCP relay request failed with status " + str(exc.code)) from exc


def _state_path(agent):
    return agent.data / STATE_FILE


def _read_state(agent):
    try:
        value = json.loads(_state_path(agent).read_text(encoding="utf-8"))
        if isinstance(value, dict):
            return {"cursor": value.get("cursor", "") if isinstance(value.get("cursor", ""), str) else "",
                    "published": value.get("published", []) if isinstance(value.get("published", []), list) else []}
    except (OSError, ValueError, TypeError):
        pass
    return {"cursor": "", "published": []}


def _write_state(agent, state):
    agent.atomic_text(_state_path(agent), json.dumps(state, ensure_ascii=False, separators=(",", ":")))


def sync_once(agent):
    """Publish new local FOSCP patches, then pull and apply the remote feed."""
    identity = code_sync._device_identity(agent.data)
    state = _read_state(agent)
    published = {item for item in state["published"] if isinstance(item, str)}
    sent = received = skipped = 0
    last_error = None

    for row in reversed(code_sync.history(agent, limit=200)):
        change_id = row.get("id")
        if not isinstance(change_id, str) or change_id in published:
            continue
        try:
            message = code_sync.get_message(agent, change_id)
            _post("publish", {"device_id": identity["id"], "device_token": identity["token"],
                               "message": message})
            published.add(change_id)
            sent += 1
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last_error = str(exc)[:200]
            break

    try:
        result = _post("pull", {"device_id": identity["id"], "device_token": identity["token"],
                                 "cursor": state["cursor"], "limit": MAX_PULL})
        updates = result.get("updates", [])
        if not isinstance(updates, list) or len(updates) > MAX_PULL:
            raise ValueError("FOSCP relay returned an invalid update batch")
        for item in updates:
            if not isinstance(item, dict) or not isinstance(item.get("message"), dict):
                skipped += 1
                continue
            message = item["message"]
            change_id = message.get("id")
            origin_id = message.get("origin", {}).get("device_id", "unknown")
            try:
                with agent.lock:
                    if not code_sync._record_path(agent, change_id).exists():
                        code_sync.apply_message(agent, message, source="peer-cloud:" + str(origin_id)[:32])
                        received += 1
            except (ValueError, OSError):
                skipped += 1
            if isinstance(change_id, str):
                published.add(change_id)
        cursor = result.get("cursor", state["cursor"])
        if isinstance(cursor, str):
            state["cursor"] = cursor
    except (OSError, ValueError, urllib.error.URLError) as exc:
        last_error = str(exc)[:200]

    ordered_published = [item for item in state["published"] if isinstance(item, str)]
    for row in reversed(code_sync.history(agent, limit=200)):
        change_id = row.get("id")
        if isinstance(change_id, str) and change_id in published and change_id not in ordered_published:
            ordered_published.append(change_id)
    state["published"] = ordered_published[-MAX_PUBLISHED_IDS:]
    _write_state(agent, state)
    status = {"configured": True, "status": "connected" if not last_error else "error",
              "last_sync": time.time(), "sent": sent, "received": received,
              "skipped": skipped, "error": last_error}
    agent.f2f_relay_status = status
    return status


def worker(agent, stop_event, interval=POLL_SECONDS):
    """Retry a brief HTTPS poll; no persistent worker or server process is used."""
    while not stop_event.is_set():
        if not configured():
            agent.f2f_relay_status = {"configured": False, "status": "unconfigured"}
        else:
            try:
                sync_once(agent)
            except Exception as exc:
                agent.f2f_relay_status = {"configured": True, "status": "error",
                    "last_sync": time.time(), "error": str(exc)[:200]}
        if stop_event.wait(interval):
            return
