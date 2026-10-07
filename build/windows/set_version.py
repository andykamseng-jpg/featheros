"""Bake the requested release version before PyInstaller collects modules."""
from pathlib import Path
import re
import sys


def bake_version(version, target):
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("Release version must be MAJOR.MINOR.PATCH")
    Path(target).write_text(
        '\"\"\"Feather local agent; release version is baked into packaged builds.\"\"\"\n\n'
        + '__version__ = ' + repr(version) + '\n', encoding="utf-8")


if __name__ == "__main__":
    bake_version(sys.argv[1], Path(__file__).resolve().parents[2] / "agent" / "__init__.py")
