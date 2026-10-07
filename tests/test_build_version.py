import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest


class BuildVersionTests(unittest.TestCase):
    def test_baked_version_survives_missing_or_wrong_runtime_environment(self):
        script = Path(__file__).resolve().parents[1] / 'build/windows/set_version.py'
        bake = runpy.run_path(str(script))['bake_version']
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / '__init__.py'
            bake('9.8.7', target)
            env = dict(os.environ, FEATHER_VERSION='0.0.0')
            result = subprocess.run([sys.executable, '-c', 'import runpy,sys; print(runpy.run_path(sys.argv[1])["__version__"])', str(target)], env=env, capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.strip(), '9.8.7')
            with self.assertRaises(ValueError):
                bake('invalid', target)
            self.assertEqual(runpy.run_path(str(target))['__version__'], '9.8.7')
