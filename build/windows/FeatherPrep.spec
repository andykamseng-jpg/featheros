"""PyInstaller one-file builds for the FeatherPrep GUI and FeatherMCP stdio app."""
from pathlib import Path
import os

ROOT = Path(SPECPATH).resolve().parents[1]
is_mcp = os.environ.get("FEATHER_MCP_BUILD") == "1"
datas = [(str(ROOT / "agent" / "desktop.html"), "agent")]
for folder in ("agent", "windows", "design"):
    for source in (ROOT / folder).rglob("*"):
        if source.is_file() and source.suffix.lower() in {".py", ".ps1", ".html", ".md"}:
            datas.append((str(source), "feather-source/" + source.relative_to(ROOT).parent.as_posix()))
for name in ("README.md", "VERIFICATION.md", "launcher.py"):
    source = ROOT / name
    if source.is_file():
        datas.append((str(source), "feather-source"))

a = Analysis(
    [str(ROOT / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="FeatherMCP" if is_mcp else "FeatherPrep",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=is_mcp,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
