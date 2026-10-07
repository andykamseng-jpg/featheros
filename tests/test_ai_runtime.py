import json
import os
import tempfile
import unittest
from unittest.mock import patch

from agent import local_ai, runtime, web
from agent.capabilities import profile_hardware
from agent.core import Agent


class CapabilityTests(unittest.TestCase):
    def test_windows_inventory_is_normalized(self):
        profile = profile_hardware({
            "computer": [{"TotalPhysicalMemory": "17179869184"}],
            "processors": [{"NumberOfLogicalProcessors": 8}],
            "graphics": [{"Name": "Example GPU"}],
        })
        self.assertEqual(profile["memory_bytes"], 16 * 1024 ** 3)
        self.assertEqual(profile["cpu_threads"], 8)
        self.assertEqual(profile["resource_band"], "expanded")
        self.assertEqual(profile["gpu_names"], ["Example GPU"])
        self.assertEqual(profile["fit_status"], "benchmark_required")

    def test_linux_inventory_is_normalized(self):
        profile = profile_hardware({"memory_total_kib": 4194304}, cpu_threads=4)
        self.assertEqual(profile["memory_bytes"], 4 * 1024 ** 3)
        self.assertEqual(profile["cpu_threads"], 4)
        self.assertEqual(profile["local_model_hint"], "online_or_tiny_local_candidate")

    def test_missing_or_malformed_inventory_is_safe(self):
        profile = profile_hardware({"computer": "invalid", "memory_total_kib": "unknown"}, cpu_threads=0)
        self.assertIsNone(profile["memory_bytes"])
        self.assertEqual(profile["resource_band"], "unknown")
        self.assertEqual(profile["fit_status"], "benchmark_required")

    def test_system_info_includes_ai_resource_profile(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory, \
             patch("agent.core.platform.system", return_value="Linux"), \
             patch("agent.core.linux_hardware_inventory", return_value={"memory_total_kib": 4096}):
            agent = Agent(os.path.join(directory, "data"), os.path.join(directory, "source"))
            self.assertTrue(agent.hardware_ready.wait(2))
            result = agent.call("system_info", {})
        self.assertEqual(result["ai_capabilities"]["fit_status"], "benchmark_required")


class LocalAIConfigurationTests(unittest.TestCase):
    def test_requires_model_and_loopback_endpoint(self):
        with patch.dict(os.environ, {
            "FEATHER_LOCAL_AI_URL": "http://127.0.0.1:1234/v1/chat/completions",
            "FEATHER_LOCAL_AI_MODEL": "feather-small",
        }, clear=True):
            self.assertTrue(local_ai.configured())
        with patch.dict(os.environ, {
            "FEATHER_LOCAL_AI_URL": "http://192.168.1.10:1234/v1/chat/completions",
            "FEATHER_LOCAL_AI_MODEL": "feather-small",
        }, clear=True):
            self.assertFalse(local_ai.configured())
        self.assertIsNone(local_ai.validate_configuration(
            "http://user@localhost:1234/v1/chat/completions", "feather-small"))

    def test_local_precedes_online_by_default_and_online_can_be_selected(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(local_ai, "configured", return_value=True), \
             patch.object(runtime.cloud, "configured", return_value=True):
            self.assertEqual(runtime.selected_backend(), "local")
        with patch.dict(os.environ, {"FEATHER_AI_MODE": "online"}, clear=True), \
             patch.object(local_ai, "configured", return_value=True), \
             patch.object(runtime.cloud, "configured", return_value=True):
            self.assertEqual(runtime.selected_backend(), "online")
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(local_ai, "configured", return_value=False), \
             patch.object(runtime.cloud, "configured", return_value=True):
            self.assertEqual(runtime.selected_backend(), "online")

    def test_agent_keeps_bounded_context_separate_per_conversation(self):
        with tempfile.TemporaryDirectory() as directory:
            agent = Agent(os.path.join(directory, "data"), os.path.join(directory, "source"))
            conversation = "12345678-1234-4234-8234-123456789abc"
            first = agent.submit("first question", conversation)
            self.assertEqual(first["conversation_id"], conversation)
            agent.call("task_next", {})
            agent.call("task_reply", {"id": first["id"], "text": "first answer"})
            second = agent.submit("different conversation", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
            agent.call("task_next", {})
            agent.call("task_reply", {"id": second["id"], "text": "separate answer"})
            self.assertEqual(agent.conversation_context(first["conversation_id"]), [
                {"role": "user", "content": "first question"},
                {"role": "assistant", "content": "first answer"},
            ])
            self.assertEqual(agent.conversation_context("missing"), [])
            with self.assertRaises(ValueError):
                agent.submit("invalid ID", "not-a-uuid")
        with patch.object(local_ai, "configured", return_value=False), \
             patch.object(runtime.cloud, "configured", return_value=True):
            self.assertEqual(runtime.selected_backend(), "online")


class _Response:
    def __init__(self, payload):
        self.data = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, limit):
        return self.data


class _Agent:
    def __init__(self):
        self.calls = []
        self.context = []

    def conversation_context(self, conversation_id):
        self.context_id = conversation_id
        return list(self.context)

    def call(self, name, arguments):
        self.calls.append((name, arguments))
        return {"os": "TestOS"}


class LocalAIRunTests(unittest.TestCase):
    def test_local_completion_uses_loopback_without_api_key(self):
        payload = {"choices": [{"message": {"role": "assistant", "content": "Hello from Feather"}}]}
        with patch.dict(os.environ, {
            "FEATHER_LOCAL_AI_URL": "http://localhost:1234/v1/chat/completions",
            "FEATHER_LOCAL_AI_MODEL": "feather-small",
        }, clear=True), patch("agent.local_ai.urllib.request.urlopen", return_value=_Response(payload)) as open_url:
            reply = local_ai.run_task(_Agent(), "hello")
        self.assertEqual(reply, "Hello from Feather")
        request = open_url.call_args.args[0]
        self.assertEqual(request.full_url, "http://localhost:1234/v1/chat/completions")
        self.assertIsNone(request.get_header("Authorization"))

    def test_local_request_receives_bounded_history_for_current_conversation(self):
        payload = {"choices": [{"message": {"role": "assistant", "content": "I remember."}}]}
        agent = _Agent()
        agent.context = [{"role": "user", "content": "My name is Alex."},
                         {"role": "assistant", "content": "Hello, Alex."}]
        with patch.dict(os.environ, {
            "FEATHER_LOCAL_AI_URL": "http://127.0.0.1:1234/v1/chat/completions",
            "FEATHER_LOCAL_AI_MODEL": "feather-small",
        }, clear=True), patch("agent.local_ai.urllib.request.urlopen", return_value=_Response(payload)) as open_url:
            local_ai.run_task(agent, "What is my name?", "12345678-1234-4234-8234-123456789abc")
        sent = json.loads(open_url.call_args.args[0].data)
        self.assertEqual(sent["messages"][1:3], agent.context)
        self.assertEqual(sent["messages"][3], {"role": "user", "content": "What is my name?"})
        self.assertEqual(agent.context_id, "12345678-1234-4234-8234-123456789abc")

    def test_local_model_can_use_read_only_hardware_tool(self):
        payload = {"choices": [{"message": {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "call-1", "function": {
                "name": "system_info", "arguments": "{}"
            }}],
        }}]}
        final = {"choices": [{"message": {"role": "assistant", "content": "Hardware scan complete."}}]}
        agent = _Agent()
        with patch.dict(os.environ, {
            "FEATHER_LOCAL_AI_URL": "http://127.0.0.1:1234/v1/chat/completions",
            "FEATHER_LOCAL_AI_MODEL": "feather-small",
        }, clear=True), patch("agent.local_ai.urllib.request.urlopen", side_effect=[_Response(payload), _Response(final)]):
            reply = local_ai.run_task(agent, "check this PC")
        self.assertEqual(reply, "Hardware scan complete.")
        self.assertEqual(agent.calls, [("system_info", {})])


class LocalWebToolsTests(unittest.TestCase):
    def test_search_returns_bounded_parsed_results(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def read(self, limit):
                return (b'<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage">'
                        b'Example &amp; result</a><a class="result__snippet">A useful result.</a>')
        with patch("agent.web.urllib.request.urlopen", return_value=Response()):
            result = web.search_web("Feather AI")
        self.assertEqual(result["query"], "Feather AI")
        self.assertEqual(result["results"], [{
            "title": "Example & result", "url": "https://example.com/page", "snippet": "A useful result."
        }])

    def test_open_browser_accepts_only_http_urls(self):
        with patch("agent.web.webbrowser.open_new_tab", return_value=True) as open_tab:
            result = web.open_in_browser("https://example.com/path")
        self.assertTrue(result["opened"])
        open_tab.assert_called_once_with("https://example.com/path")
        for url in ("javascript:alert(1)", "file:///etc/passwd", "https://user@example.com"):
            with self.assertRaises(ValueError):
                web.open_in_browser(url)

    def test_web_actions_are_available_to_the_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            agent = Agent(os.path.join(directory, "data"), os.path.join(directory, "source"))
            with patch("agent.web.search_web", return_value={"results": []}) as search:
                self.assertEqual(agent.call("web_search", {"query": "Feather"}), {"results": []})
            search.assert_called_once_with("Feather")


if __name__ == "__main__":
    unittest.main()

