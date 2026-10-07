"""Select the configured Feather AI provider and process queued requests."""
import json
import threading
from . import cloud, local_ai


def provider_path(agent):
    return agent.data / "ai-provider.json"


def selected_provider(agent):
    try:
        value = json.loads(provider_path(agent).read_text(encoding="utf-8"))
        if value.get("provider") in {"local", "online"}:
            return value["provider"]
    except (OSError, ValueError, TypeError):
        pass
    return "local"


def select_provider(agent, provider):
    if provider not in {"local", "online"}:
        raise ValueError("Unknown AI provider")
    agent.atomic_text(provider_path(agent), json.dumps({"provider": provider}))


def configured(agent):
    provider = selected_provider(agent)
    return local_ai.configured(agent.data) if provider == "local" else cloud.configured()


def status(agent):
    provider = selected_provider(agent)
    local = local_ai.load_settings(agent.data)
    return {"provider": provider, "configured": configured(agent),
            "model": local["model"] if provider == "local" and local else None,
            "context": "Each task starts without previous chat context."}


def run_task(agent, text):
    provider = selected_provider(agent)
    if provider == "local":
        return local_ai.run_task(agent, text)
    if not cloud.configured():
        raise ValueError("Online AI was selected but is not connected")
    return cloud.run_task(agent, text)


def worker(agent, stop):
    while not stop.is_set():
        task = agent.call("task_next", {})
        if "id" not in task:
            stop.wait(1)
            continue
        try:
            reply = run_task(agent, task["text"])
        except Exception as exc:
            provider = selected_provider(agent)
            reply = provider.title() + " AI request failed (" + type(exc).__name__ + "). Check the selected provider; no automatic retry was made."
        agent.call("task_reply", {"id": task["id"], "text": reply})
