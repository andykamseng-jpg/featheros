import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import updater


class UpdaterTests(unittest.TestCase):
    def release(self, digest=None, url=None, size=7, tag="v0.6.6"):
        return {"tag_name": tag, "assets": [{
            "name": "FeatherOS-Setup.exe", "size": size,
            "browser_download_url": url or updater.ASSET_URL_PREFIX + tag + "/FeatherOS-Setup.exe",
            "digest": "sha256:" + (digest or hashlib.sha256(b"release").hexdigest()),
        }]}

    def test_accepts_only_newer_official_release_with_hash(self):
        self.assertIsNotNone(updater.release_installer(self.release()))
        self.assertIsNone(updater.release_installer(self.release(tag="v0.6.3")))
        self.assertIsNone(updater.release_installer(self.release(url="https://example.invalid/setup.exe")))
        self.assertIsNone(updater.release_installer(self.release(size=updater.MAX_INSTALLER_BYTES + 1)))
        self.assertIsNone(updater.release_installer(self.release(digest="bad")))

    def test_stages_only_verified_exact_size(self):
        release = updater.release_installer(self.release())
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(updater.urllib.request, "urlopen", return_value=io.BytesIO(b"release")):
                path = updater.stage_release(directory, release)
            self.assertEqual(path.read_bytes(), b"release")
            path.unlink()
            with patch.object(updater.urllib.request, "urlopen", return_value=io.BytesIO(b"tampered")):
                with self.assertRaises(ValueError):
                    updater.stage_release(directory, release)
            self.assertFalse(path.exists())
            self.assertFalse(Path(directory, "updates", "FeatherOS-Setup-v0.6.6.partial").exists())


if __name__ == "__main__":
    unittest.main()
