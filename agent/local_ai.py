"""Local OpenAI-compatible model adapter.

The endpoint must be on loopback so Feather never sends local tasks to another
machine without an explicit future network-provider design.
"""
import json
import os
from urllib.parse import urlparse
import urllib.request

from .core import TOOLS


MAX_RESPONSE_BYTES = 2 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 180


def validate_configuration(endpoint, model):
    endpoint = str(endpoint or "").strip()
    model = str(model or "").strip()
    parsed = urlparse(endpoint)
    if (not model or parsed.scheme not in {"http", "https"} or
            parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or
            parsed.username or parsed.password or not parsed.path):
        return None
    return {"endpoint": endpoint, "model": model}


def configuration():
    return validate_configuration(
        os.environ.get("FEATHER_LOCAL_AI_URL", ""),
        os.environ.get("FEATHER_LOCAL_AI_MODEL", ""),
    )


def configured():
    return configuration() is not None


def run_task(agent, text, conversation_id=None):
    """Run a queued task through the configured local model and Feather tools."""
    config = configuration()
    if not config:
        raise RuntimeError("Local AI is not configured for this computer")
    tools = [tool for tool in TOOLS if not tool["name"].startswith("task_")]
    messages = [
        {"role": "system", "content": "You operate Feather through its local tools. "
         "Inspect before changing files. Use root=source for Feather code and root=workspace for user projects. "
         "Save a revision before edits. Run relevant verification when commands are enabled. "
         "Do not claim an OS install or test happened without evidence. Report changes and limitations."},
    ]
    if hasattr(agent, "conversation_context"):
        messages.extend(agent.conversation_context(conversation_id))
    messages.append({"role": "user", "content": text})

    for _ in range(8):
        payload = {
            "model": config["model"],
            "messages": messages,
            "tools": [{"type": "function", "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["inputSchema"],
            }} for tool in tools],
        }
        request = urllib.request.Request(
            config["endpoint"],
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "FeatherOS-Local-AI"},
        )
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            data = response.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            raise ValueError("Local AI response exceeds size limit")
        try:
            message = json.loads(data)["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ValueError("Local AI returned an invalid chat response") from exc
        if not isinstance(message, dict):
            raise ValueError("Local AI returned an invalid chat response")
        messages.append(message)
        calls = message.get("tool_calls") or []
        if not calls:
            return message.get("content") or "The local AI returned no text."

        for call in calls[:12]:
            try:
                name = call["function"]["name"]
                arguments = json.loads(call["function"]["arguments"])
                if name not in {tool["name"] for tool in tools}:
                    raise ValueError("Unknown local AI tool")
                result = agent.call(name, arguments)
            except Exception as exc:
                result = {"error": str(exc)}
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id", ""),
                "content": json.dumps(result, ensure_ascii=False),
            })
        if len(calls) > 12:
            return "Task stopped after too many tool calls. Some calls may already have completed."

    return "Task paused after eight AI rounds. Check current files before continuing."

