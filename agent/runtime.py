"""Prefer the local model, with an explicit online override."""
import os

from . import cloud, local_ai


def selected_backend():
    preference = os.environ.get("FEATHER_AI_MODE", "auto").strip().lower()
    if preference == "online" and cloud.configured():
        return "online"
    if preference == "local" and local_ai.configured():
        return "local"
    if local_ai.configured():
        return "local"
    if cloud.configured():
        return "online"
    return "none"


def configured():
    return selected_backend() != "none"


def run_task(agent, text, conversation_id=None):
    backend = selected_backend()
    if backend == "local":
        return local_ai.run_task(agent, text, conversation_id)
    if backend == "online":
        return cloud.run_task(agent, text, conversation_id)
    raise RuntimeError("No local or online AI provider is configured")


def worker(agent, stop):
    while not stop.is_set():
        task = agent.call("task_next", {})
        if "id" not in task:
            stop.wait(1)
            continue
        try:
            reply = run_task(agent, task["text"], task.get("conversation_id"))
        except Exception as exc:
            reply = "AI request failed (" + type(exc).__name__ + "). Check the selected provider; no automatic retry was made."
        agent.call("task_reply", {"id": task["id"], "text": reply})

