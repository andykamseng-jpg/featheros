"""Loopback-only OpenAI-compatible local model adapter."""
import ipaddress
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlparse
import urllib.request

from .core import TOOLS


def validate_endpoint(endpoint):
    parsed = urlparse(str(endpoint or ""))
    host = (parsed.hostname or "").lower().rstrip(".")
    if (parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise ValueError("Local AI endpoint must be an HTTP(S) URL on loopback")
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host == "localhost"
    if not loopback or not parsed.port:
        raise ValueError("Local AI endpoint must use localhost or a loopback IP and an explicit port")
    return endpoint


def settings_path(data_dir):
    return Path(data_dir) / "local-ai.json"


def load_settings(data_dir):
    try:
        value = json.loads(settings_path(data_dir).read_text(encoding="utf-8"))
        endpoint = validate_endpoint(value.get("endpoint"))
        model = value.get("model")
        if isinstance(model, str) and model.strip() and len(model) <= 120:
            return {"endpoint": endpoint, "model": model.strip()}
    except (OSError, ValueError, TypeError):
        pass
    return None


def save_settings(data_dir, endpoint, model):
    validate_endpoint(endpoint)
    model = str(model or "").strip()
    if not model or len(model) > 120 or any(ord(ch) < 32 for ch in model):
        raise ValueError("Enter a valid local model name")
    path = settings_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".local-ai-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump({"endpoint": endpoint, "model": model}, output, ensure_ascii=False)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return {"endpoint": endpoint, "model": model}


def configured(data_dir):
    return load_settings(data_dir) is not None


class _LoopbackRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        validate_endpoint(new_url)
        return super().redirect_request(request, response, code, message, headers, new_url)


# Ignore HTTP_PROXY/HTTPS_PROXY from the environment: local prompts and hardware
# summaries must never be sent through an external proxy.
_LOOPBACK_OPENER = urllib.request.build_opener(_LoopbackRedirect)
for _handler in _LOOPBACK_OPENER.handlers:
    if isinstance(_handler, urllib.request.ProxyHandler):
        _handler.proxies = {}


def run_task(agent, text):
    settings = load_settings(agent.data)
    if not settings:
        raise ValueError("Local AI is not configured")
    messages = [
        {"role": "system", "content": "You are Feather's local assistant. Use the saved, read-only hardware summary below when inspecting this PC. Use root=workspace for user projects and root=source for Feather code. Save a revision before changing files and verify relevant changes. Do not claim an OS install or browser action happened without evidence. Browser automation is not available. Hardware model fit requires local benchmarking.\n\nSaved local hardware profile: " + json.dumps(agent.hardware_context(), ensure_ascii=False)},
        {"role": "user", "content": text},
    ]
    # Hardware details are already supplied as a compact summary above.
    # Do not offer the raw inventory (which can contain unique device paths) as a model tool.
    tools = [tool for tool in TOOLS
             if not tool["name"].startswith("task_") and tool["name"] != "system_info"]
    for _ in range(8):
        payload = {"model": settings["model"], "messages": messages,
                   "tools": [{"type": "function", "function": {
                       "name": tool["name"], "description": tool["description"],
                       "parameters": tool["inputSchema"]}} for tool in tools]}
        request = urllib.request.Request(settings["endpoint"], data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Accept": "application/json"})
        with _LOOPBACK_OPENER.open(request, timeout=60) as response:
            body = response.read(2 * 1024 * 1024 + 1)
            if len(body) > 2 * 1024 * 1024:
                raise ValueError("Local AI response exceeds size limit")
            message = json.loads(body)["choices"][0]["message"]
        messages.append(message)
        calls = message.get("tool_calls") or []
        if not calls:
            return message.get("content") or "The local AI returned no text."
        for call in calls[:12]:
            name = call["function"]["name"]
            try:
                if name not in {tool["name"] for tool in tools}:
                    raise ValueError("Unknown local tool")
                result = agent.call(name, json.loads(call["function"]["arguments"]))
            except Exception as exc:
                result = {"error": str(exc)}
            messages.append({"role": "tool", "tool_call_id": call["id"],
                             "content": json.dumps(result, ensure_ascii=False)})
        if len(calls) > 12:
            return "Task stopped: too many tool calls in one response. Some calls may already have completed."
    return "Task paused after eight AI rounds. Check the activity and current files before continuing."
