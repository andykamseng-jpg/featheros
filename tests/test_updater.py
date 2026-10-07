import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import updater


class UpdaterTests(unittest.TestCase):
    def release(self, digest=None, url=None, size=7, tag="v0.6.12"):
        return {"tag_name": tag, "assets": [{
            "name": "FeatherOS-Setup.exe", "size": size,
            "browser_download_url": url or updater.ASSET_URL_PREFIX + tag + "/FeatherOS-Setup.exe",
            "digest": "sha256:" + (digest or hashlib.sha256(b"release").hexdigest()),
        }]}

    def test_accepts_only_newer_official_release_with_hash(self):
        self.assertIsNotNone(updater.release_installer(self.release(), current="0.6.11"))
        self.assertIsNone(updater.release_installer(self.release(tag="v0.6.3"), current="0.6.11"))
        self.assertIsNone(updater.release_installer(self.release(url="https://example.invalid/setup.exe"), current="0.6.11"))
        self.assertIsNone(updater.release_installer(self.release(size=updater.MAX_INSTALLER_BYTES + 1), current="0.6.11"))
        self.assertIsNone(updater.release_installer(self.release(digest="bad"), current="0.6.11"))

    def test_same_or_older_installed_release_never_reinstalls(self):
        self.assertIsNone(updater.release_installer(self.release(), current="0.6.12"))
        self.assertIsNone(updater.release_installer(self.release(), current="0.6.13"))

    def test_launch_claim_survives_restart_and_blocks_duplicate_processes(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(updater, '__version__', '0.6.11'), patch.object(updater.subprocess, 'Popen') as start:
            self.assertTrue(updater.launch_installer(directory, 'setup.exe', 'v0.6.12'))
            self.assertFalse(updater.launch_installer(directory, 'setup.exe', 'v0.6.12'))
            self.assertTrue(updater.launch_installer(directory, 'setup.exe', 'v0.6.13'))
            self.assertEqual(start.call_count, 2)

    def test_failed_process_start_can_retry_and_installed_release_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(updater, '__version__', '0.6.12'), patch.object(updater.subprocess, 'Popen', side_effect=OSError):
            self.assertFalse(updater.launch_installer(directory, 'setup.exe', 'v0.6.12'))
            with self.assertRaises(OSError):
                updater.launch_installer(directory, 'setup.exe', 'v0.6.13')
            self.assertFalse(Path(directory, 'updates', 'install-started-v0.6.13.json').exists())

    def test_stages_only_verified_exact_size(self):
        release = updater.release_installer(self.release(), current="0.6.11")
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(updater.urllib.request, "urlopen", return_value=io.BytesIO(b"release")):
                path = updater.stage_release(directory, release)
            self.assertEqual(path.read_bytes(), b"release")
            path.unlink()
            with patch.object(updater.urllib.request, "urlopen", return_value=io.BytesIO(b"tampered")):
                with self.assertRaises(ValueError):
                    updater.stage_release(directory, release)
            self.assertFalse(path.exists())
            self.assertFalse(Path(directory, "updates", "FeatherOS-Setup-v0.6.12.partial").exists())


if __name__ == "__main__":
    unittest.main()
