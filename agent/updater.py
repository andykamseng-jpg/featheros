"""Download a verified official FeatherOS release before restarting the installer."""
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.request

from . import __version__


RELEASE_URL = "https://api.github.com/repos/andykamseng-jpg/featheros/releases/latest"
ASSET_URL_PREFIX = "https://github.com/andykamseng-jpg/featheros/releases/download/"
MAX_INSTALLER_BYTES = 80 * 1024 * 1024


def _version(value):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(value or ""))
    return tuple(map(int, match.groups())) if match else None


def release_installer(metadata, current=__version__):
    """Accept only a newer tagged installer from the expected repository."""
    if not isinstance(metadata, dict):
        return None
    tag = metadata.get("tag_name")
    if not _version(tag) or _version(tag) <= _version(current):
        return None
    for asset in metadata.get("assets", []):
        if not isinstance(asset, dict) or asset.get("name") != "FeatherOS-Setup.exe":
            continue
        url = asset.get("browser_download_url", "")
        digest = asset.get("digest", "")
        size = asset.get("size")
        if (url == ASSET_URL_PREFIX + tag + "/FeatherOS-Setup.exe"
                and isinstance(digest, str) and re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest)
                and isinstance(size, int) and 0 < size <= MAX_INSTALLER_BYTES):
            return {"tag": tag, "url": url, "digest": digest.split(":", 1)[1].lower(), "size": size}
    return None


def _request(url):
    return urllib.request.Request(url, headers={"User-Agent": "FeatherPrep-Updater", "Accept": "application/vnd.github+json"})


def fetch_latest():
    with urllib.request.urlopen(_request(RELEASE_URL), timeout=12) as response:
        metadata = json.loads(response.read(256 * 1024 + 1))
    return release_installer(metadata)


def stage_release(data_dir, release):
    """Stream with a size cap and compare the hash advertised by GitHub."""
    folder = Path(data_dir) / "updates"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / ("FeatherOS-Setup-" + release["tag"] + ".exe")
    if target.is_file() and target.stat().st_size == release["size"]:
        if hashlib.sha256(target.read_bytes()).hexdigest() == release["digest"]:
            return target
    temp = target.with_suffix(".partial")
    digest = hashlib.sha256()
    count = 0
    try:
        with urllib.request.urlopen(_request(release["url"]), timeout=30) as response, temp.open("wb") as output:
            while chunk := response.read(64 * 1024):
                count += len(chunk)
                if count > MAX_INSTALLER_BYTES or count > release["size"]:
                    raise ValueError("Installer exceeded expected size")
                digest.update(chunk)
                output.write(chunk)
        if count != release["size"] or digest.hexdigest() != release["digest"]:
            raise ValueError("Installer hash or size did not match release metadata")
        os.replace(temp, target)
        return target
    finally:
        temp.unlink(missing_ok=True)
