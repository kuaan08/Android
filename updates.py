"""Explicit GitHub release checks and digest-verified staged update downloads."""
import hashlib
import json
from pathlib import Path
import re
import urllib.request

REPOSITORY = "kuaan08/xbo360"
API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"


def release(current, platform_name):
    request = urllib.request.Request(API, headers={"User-Agent": "Xbox360Recomp", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("Oversized release response")
    data = json.loads(raw)
    url = data.get("html_url", "")
    if not url.startswith(f"https://github.com/{REPOSITORY}/releases/tag/"):
        raise ValueError("Unexpected release repository")
    desired = {"win-amd64": "Xbox360Recomp-Windows-x64.zip",
               "android-arm64": "Xbox360Recomp-Android.apk"}.get(platform_name)
    asset = next((a for a in data.get("assets", []) if a.get("name") == desired), None)
    tag = data.get("tag_name", "")
    if not re.fullmatch(r"v?\d+\.\d+\.\d+(?:[-+.][A-Za-z0-9.-]+)?", tag):
        raise ValueError("Release has an unsupported version tag")
    numeric = lambda v: tuple(int(n) for n in re.findall(r"\d+", v)[:3])
    return {"version": tag, "current": numeric(current) >= numeric(tag), "url": url,
            "asset": asset, "notes": data.get("body", "")[:10000]}


def download(info, directory):
    asset = info.get("asset")
    if not asset:
        raise ValueError("No update package is published for this platform")
    name = asset["name"]
    if name not in ("Xbox360Recomp-Windows-x64.zip", "Xbox360Recomp-Android.apk"):
        raise ValueError("Unexpected update filename")
    url = asset["browser_download_url"]
    if not url.startswith(f"https://github.com/{REPOSITORY}/releases/download/"):
        raise ValueError("Unexpected update download source")
    digest = asset.get("digest", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("Release asset has no SHA-256 digest; refusing an unverified download")
    if not isinstance(asset.get("size"), int) or not 0 < asset["size"] <= 2 * 1024**3:
        raise ValueError("Invalid update package size")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    partial = target.with_suffix(target.suffix + ".part")
    sha = hashlib.sha256()
    size = 0
    try:
        with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as out:
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > asset["size"]:
                    raise ValueError("Update exceeds its published size")
                out.write(chunk)
                sha.update(chunk)
        if size != asset["size"] or "sha256:" + sha.hexdigest() != digest:
            raise ValueError("Update integrity verification failed")
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return target
