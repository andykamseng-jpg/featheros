import re
import unittest
from pathlib import Path


class InstallerFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = (Path(__file__).resolve().parents[1] /
                      'build' / 'windows' / 'FeatherOS.iss').read_text(encoding='utf-8')

    def test_running_app_is_closed_before_restart_manager_checks_locked_files(self):
        self.assertIn('function PrepareToInstall(var NeedsRestart: Boolean): String;', self.script)
        self.assertIn('CloseMainWindow()', self.script)
        self.assertIn('Wait-Process -Timeout 8', self.script)
        self.assertIn('Stop-Process -Force', self.script)
        self.assertIn("'{sys}\\taskkill.exe'", self.script)
        self.assertIn('CloseApplications=force', self.script)

    def test_installer_launches_app_and_closes_without_finish_click(self):
        self.assertIn('DisableFinishedPage=yes', self.script)
        run_section = re.search(r'\[Run\](.*?)(?:\n\[|\Z)', self.script, re.S).group(1)
        self.assertRegex(run_section, r'Filename: "\{app\}\\FeatherPrep\\FeatherPrep\.exe"; Flags: nowait')
        self.assertNotIn('postinstall', run_section)


if __name__ == '__main__':
    unittest.main()
