"""Optional cloud agent using a configured chat-completions-compatible endpoint.

No provider account or model is bundled. Model requests occur only for queued tasks.
"""
import json
import os
import time
import urllib.request
from urllib.parse import urlparse
from .core import TOOLS


def configured():
    return all(os.environ.get(k) for k in ("FEATHER_AI_URL", "FEATHER_AI_KEY", "FEATHER_AI_MODEL"))


def run_task(agent, text, conversation_id=None):
    endpoint = os.environ["FEATHER_AI_URL"]
    if urlparse(endpoint).scheme != "https":
        raise ValueError("Cloud AI endpoint must use HTTPS")
    tools = [t for t in TOOLS if not t["name"].startswith("task_")]
    messages = [
        {"role": "system", "content": "You operate Feather through its tools. Inspect before changing files. "
         "Use root=source for Feather code and root=workspace for user projects. Save a revision before edits. "
         "Run relevant verification when commands are enabled. Do not claim an OS install or test happened "
         "without evidence. Source edits may require restart. Report what changed and any remaining limitations."},
    ]
    if hasattr(agent, "conversation_context"):
        messages.extend(agent.conversation_context(conversation_id))
    messages.append({"role": "user", "content": text})
    for _ in range(8):
        payload = {"model": os.environ["FEATHER_AI_MODEL"], "messages": messages,
                   "tools": [{"type": "function", "function": {
                       "name": t["name"], "description": t["description"],
                       "parameters": t["inputSchema"]}} for t in tools]}
        request = urllib.request.Request(endpoint, data=json.dumps(payload).encode(),
            headers={"Authorization": "Bearer " + os.environ["FEATHER_AI_KEY"],
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=45) as response:
            data = response.read(2 * 1024 * 1024 + 1)
            if len(data) > 2 * 1024 * 1024:
                raise ValueError("AI response exceeds size limit")
            message = json.loads(data)["choices"][0]["message"]
        messages.append(message)
        calls = message.get("tool_calls") or []
        if not calls:
            return message.get("content") or "The AI returned no text."
        for c in calls[:12]:
            name = c["function"]["name"]
            try:
                if name not in {t["name"] for t in tools}:
                    raise ValueError("Unknown cloud tool")
                result = agent.call(name, json.loads(c["function"]["arguments"]))
            except Exception as e:
                result = {"error": str(e)}
            messages.append({"role": "tool", "tool_call_id": c["id"],
                             "content": json.dumps(result, ensure_ascii=False)})
        if len(calls) > 12:
            return "Task stopped: too many tool calls in one response. Some calls may already have completed."
    return "Task paused after eight AI rounds. Check the activity and current files before continuing."


def worker(agent, stop):
    while not stop.is_set():
        task = agent.call("task_next", {})
        if "id" not in task:
            stop.wait(1)
            continue
        try:
            reply = run_task(agent, task["text"])
        except Exception as e:
            # Provider error text can contain confidential request information.
            reply = "Cloud request failed (" + type(e).__name__ + "). Check your provider configuration; no automatic retry was made."
        agent.call("task_reply", {"id": task["id"], "text": reply})

