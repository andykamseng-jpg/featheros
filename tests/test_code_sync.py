import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from agent.core import Agent
from agent import code_sync, f2f_cloud
from agent.server import _sync_peer, start_peer_sync, stop_peer_sync


class CodeSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source_a = self.root / "source-a"
        self.source_b = self.root / "source-b"
        self.source_a.mkdir()
        self.source_b.mkdir()
        for source in (self.source_a, self.source_b):
            (source / "agent.py").write_text("VALUE = 1\n", encoding="utf-8")
        stub = {"collection_mode": "read_only", "status": "test", "model": "test-pc"}
        self.patches = [
            patch("agent.core.windows_hardware_inventory", return_value=stub),
            patch("agent.core.linux_hardware_inventory", return_value=stub),
        ]
        for item in self.patches:
            item.start()
        self.sender = Agent(self.root / "data-a", self.source_a)
        self.receiver = Agent(self.root / "data-b", self.source_b)
        self.assertTrue(self.sender.hardware_ready.wait(3))
        self.assertTrue(self.receiver.hardware_ready.wait(3))

    def tearDown(self):
        stop_peer_sync(self.receiver)
        for thread in threading.enumerate():
            if thread.name == "feather-hardware-scan":
                thread.join(timeout=2)
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_source_write_becomes_auditable_patch(self):
        result = self.sender.call("file_write", {"root": "source", "path": "agent.py",
            "content": "VALUE = 2\n", "summary": "Improve Feather"})
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["protocol"], "FOSCP/1")
        self.assertEqual((self.source_a / "agent.py").read_text(), "VALUE = 2\n")
        record = self.sender.call("code_change_export", {"id": result["change_id"]})
        self.assertIn("integrity_sha256", record)
        self.assertIn("edits", record["changes"][0])
        self.assertNotIn("after", record["changes"][0])
        preview = code_sync.preview_message(record)
        self.assertIn("-VALUE = 1", preview)
        self.assertIn("+VALUE = 2", preview)
        self.assertEqual(self.sender.call("code_change_history", {})[0]["summary"], "Improve Feather")

    def test_related_files_apply_and_transfer_as_one_atomic_patch(self):
        changes = json.dumps([
            {"path": "agent.py", "content": "VALUE = 3\n"},
            {"path": "new_module.py", "content": "READY = True\n"},
        ])
        update = self.sender.call("code_patch_apply", {"changes": changes, "summary": "Two-file update"})
        message = self.sender.call("code_change_export", {"id": update["change_id"]})
        self.assertEqual([item["path"] for item in message["changes"]], ["agent.py", "new_module.py"])
        self.assertEqual(code_sync.apply_message(self.receiver, message)["status"], "applied")
        self.assertEqual((self.source_b / "agent.py").read_text(), "VALUE = 3\n")
        self.assertEqual((self.source_b / "new_module.py").read_text(), "READY = True\n")

    def test_batch_conflict_does_not_partially_apply(self):
        changes = json.dumps([
            {"path": "agent.py", "content": "VALUE = 8\n"},
            {"path": "new_module.py", "content": "READY = True\n"},
        ])
        update = self.sender.call("code_patch_apply", {"changes": changes, "summary": "Two-file update"})
        message = self.sender.call("code_change_export", {"id": update["change_id"]})
        (self.source_b / "new_module.py").write_text("already there\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "base does not match"):
            code_sync.apply_message(self.receiver, message)
        self.assertEqual((self.source_b / "agent.py").read_text(), "VALUE = 1\n")

    def test_peer_message_applies_once_and_records_origin(self):
        update = self.sender.call("file_write", {"root": "source", "path": "agent.py",
            "content": "VALUE = 9\n", "summary": "Peer update"})
        message = self.sender.call("code_change_export", {"id": update["change_id"]})
        result = code_sync.apply_message(self.receiver, message, source="peer:test-device")
        self.assertEqual(result["status"], "applied")
        self.assertEqual((self.source_b / "agent.py").read_text(), "VALUE = 9\n")
        repeated = code_sync.apply_message(self.receiver, message, source="peer:test-device")
        self.assertEqual(repeated["status"], "already_applied")

    def test_base_conflict_corruption_and_unsafe_path_are_rejected(self):
        update = self.sender.call("file_write", {"root": "source", "path": "agent.py",
            "content": "VALUE = 7\n"})
        message = self.sender.call("code_change_export", {"id": update["change_id"]})
        (self.source_b / "agent.py").write_text("VALUE = 4\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "base does not match"):
            code_sync.apply_message(self.receiver, message)
        corrupted = json.loads(json.dumps(message))
        corrupted["summary"] = "changed without recomputing digest"
        with self.assertRaisesRegex(ValueError, "integrity"):
            code_sync.apply_message(self.receiver, corrupted)
        with self.assertRaisesRegex(ValueError, "escapes"):
            code_sync._validate_path("../outside.py")

    def test_pairing_authentication_never_sends_the_pairing_key(self):
        payload = b'{"protocol":"FOSCP/1"}'
        proof = code_sync.peer_auth_header("temporary-secret-value-0123456789", payload)
        self.assertTrue(code_sync.verify_peer_auth("temporary-secret-value-0123456789", payload, proof))
        self.assertFalse(code_sync.verify_peer_auth("another-secret-value-0123456789", payload, proof))
        self.assertNotIn("temporary-secret-value", proof)

    def test_invalid_python_is_rejected_before_writing(self):
        with self.assertRaises(SyntaxError):
            self.sender.call("file_write", {"root": "source", "path": "agent.py",
                "content": "def broken(:\n    pass\n"})
        self.assertEqual((self.source_a / "agent.py").read_text(), "VALUE = 1\n")
        self.assertEqual(self.sender.call("code_change_history", {}), [])

    def test_hardware_paths_are_machine_bound_and_rollback_is_a_new_patch(self):
        with patch("agent.code_sync._hardware_fingerprint", return_value="matching-hardware"):
            update = self.sender.call("file_write", {"root": "source", "path": "drivers/device.inf",
                "content": "driver-version=1\n"})
        message = self.sender.call("code_change_export", {"id": update["change_id"]})
        self.assertEqual(message["compatibility"]["scope"], "machine")
        with patch("agent.code_sync._hardware_fingerprint", return_value="different-hardware"):
            with self.assertRaisesRegex(ValueError, "hardware-specific"):
                code_sync.apply_message(self.receiver, message)
        with patch("agent.code_sync._hardware_fingerprint", return_value="matching-hardware"):
            code_sync.apply_message(self.receiver, message)
        undone = self.sender.call("code_change_rollback", {"id": update["change_id"]})
        self.assertEqual(undone["status"], "applied")
        self.assertFalse((self.source_a / "drivers/device.inf").exists())

    def test_private_peer_sends_patch_without_a_bundle(self):
        try:
            with patch("agent.code_sync._lan_addresses", return_value=["127.0.0.1"]):
                peer = start_peer_sync(self.receiver, port=0)
        except OSError as exc:
            self.skipTest("local test environment does not allow opening a peer port: " + str(exc))
        update = self.sender.call("file_write", {"root": "source", "path": "agent.py",
            "content": "VALUE = 5\n", "summary": "Direct Feather sync"})
        message = code_sync.get_message(self.sender, update["change_id"])
        result = code_sync.send_message(peer["addresses"][0], self.receiver.peer_server.peer_token, message)
        self.assertEqual(result["status"], "applied")
        self.assertEqual((self.source_b / "agent.py").read_text(), "VALUE = 5\n")

    def test_automatic_peer_sync_pulls_code_messages_without_manual_address_or_key(self):
        update = self.sender.call("file_write", {"root": "source", "path": "agent.py",
            "content": "VALUE = 6\n", "summary": "Automatic F2F update"})
        message = code_sync.get_message(self.sender, update["change_id"])
        peer_id = code_sync._device_id(self.sender.data)

        def peer_get(_base, path, _token=None):
            if path == "/foscp/v1/info":
                return {"device_id": peer_id, "pairing_key": "p" * 48}
            if path == "/foscp/v1/updates":
                return {"changes": [update["change_id"]]}
            if path == "/foscp/v1/change/" + update["change_id"]:
                return message
            raise AssertionError("unexpected FOSCP route: " + path)

        with patch("agent.server._peer_get", side_effect=peer_get):
            result = _sync_peer(self.receiver, "192.168.1.20", 8766, peer_id)
        self.assertEqual(result["applied"], 1)
        self.assertEqual(result["rejected"], 0)
        self.assertEqual((self.source_b / "agent.py").read_text(), "VALUE = 6\n")
        self.assertEqual(code_sync.history(self.receiver)[0]["source"], "peer:" + peer_id)

    def test_automatic_peer_sync_rejects_a_mismatched_discovery_identity(self):
        with patch("agent.server._peer_get", return_value={
                "device_id": "b" * 32, "pairing_key": "p" * 48}):
            with self.assertRaisesRegex(ValueError, "identity did not match"):
                _sync_peer(self.receiver, "192.168.1.20", 8766, "a" * 32)

    def test_cross_network_relay_publishes_pulls_and_applies_code_message(self):
        update = self.sender.call("file_write", {"root": "source", "path": "agent.py",
            "content": "VALUE = 11\n", "summary": "Cross-network F2F update"})
        messages = []

        def relay(action, payload):
            if action == "publish":
                messages.append(payload["message"])
                return {"accepted": True}
            if action == "pull":
                items = [{"cursor": "1000|" + item["id"], "message": item} for item in messages]
                cursor = items[-1]["cursor"] if items else payload["cursor"]
                return {"updates": items[:payload["limit"]], "cursor": cursor,
                        "more": len(items) > payload["limit"]}
            raise AssertionError("unexpected F2F relay action: " + action)

        with patch("agent.f2f_cloud._post", side_effect=relay):
            first = f2f_cloud.sync_once(self.sender)
            second = f2f_cloud.sync_once(self.receiver)

        self.assertEqual(first["sent"], 1)
        self.assertEqual(second["received"], 1)
        self.assertEqual((self.source_b / "agent.py").read_text(), "VALUE = 11\n")
        self.assertEqual(code_sync.history(self.receiver)[0]["source"],
                         "peer-cloud:" + code_sync._device_id(self.sender.data))
        self.assertEqual(f2f_cloud._read_state(self.receiver)["cursor"],
                         "1000|" + update["change_id"])


if __name__ == "__main__":
    unittest.main()
