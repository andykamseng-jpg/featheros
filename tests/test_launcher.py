import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import launcher


class LauncherTests(unittest.TestCase):
    def test_seed_copies_source_once_and_keeps_user_edits(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            bundle = base / "bundle"
            source = bundle / "agent" / "core.py"
            source.parent.mkdir(parents=True)
            source.write_text("bundled", encoding="utf-8")
            source_dir = base / "saved" / "source"
            with patch.object(launcher, "bundled_source_dir", return_value=bundle):
                launcher.seed_editable_source(source_dir)
                saved = source_dir / "agent" / "core.py"
                self.assertEqual(saved.read_text(encoding="utf-8"), "bundled")
                saved.write_text("user edit", encoding="utf-8")
                launcher.seed_editable_source(source_dir)
            self.assertEqual(saved.read_text(encoding="utf-8"), "user edit")


if __name__ == "__main__":
    unittest.main()
