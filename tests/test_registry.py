import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import registry


class RegistryTests(unittest.TestCase):
    def test_identity_is_random_and_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            first = registry.get_identity(directory)
            second = registry.get_identity(directory)
            self.assertEqual(first, second)
            self.assertEqual(len(first["id"]), 32)
            self.assertEqual(len(first["token"]), 64)
            self.assertTrue(Path(directory, "device-registry.json").is_file())

    def test_report_contains_bounded_hardware_without_unique_identifiers(self):
        report = registry.make_report(
            {"id": "a" * 32, "token": "b" * 64},
            {
                "computer": [{"Manufacturer": "Test maker", "Model": "Test PC", "SerialNumber": "do-not-send"}],
                "installed_drivers": [{"DeviceName": "Wi-Fi device", "DriverVersion": "3.1", "IsSigned": True}] * 205,
                "network_hardware": [{"Name": "Wi-Fi", "PNPDeviceID": "PCI\\VEN_8086&DEV_272B&SUBSYS_ABCD\\UNIQUE"}],
                "bios": [{"Manufacturer": "Test maker", "SMBIOSBIOSVersion": "1.2", "SerialNumber": "private"}],
                "disks": [{"Model": "do-not-send"}],
            },
        )
        self.assertEqual(report["manufacturer"], "Test maker")
        self.assertEqual(report["model"], "Test PC")
        self.assertNotIn("SerialNumber", report)
        self.assertEqual(len(report["hardware"]["drivers"]), 200)
        self.assertEqual(report["hardware"]["devices"][0]["hardwareId"], "PCI\\VEN_8086&DEV_272B")
        self.assertNotIn("UNIQUE", json.dumps(report))
        self.assertNotIn("private", json.dumps(report))
        self.assertNotIn("disks", report)
        self.assertTrue(report["consent"])

    def test_unconfigured_override_does_not_generate_identity(self):
        with patch.object(registry, "REPORT_URL", ""), patch.object(registry, "UNREGISTER_URL", ""):
            self.assertFalse(registry.configured())
            with tempfile.TemporaryDirectory() as directory:
                result = registry.report_once(directory, {})
                self.assertIn("not configured", result)
                self.assertFalse(Path(directory, "device-registry.json").exists())


if __name__ == "__main__":
    unittest.main()
