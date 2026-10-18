#!/usr/bin/env python3
"""Download and safely extract only the Android NDK r27c sysroot for Termux.

The official archive contains Linux x86_64 host executables which this script
never extracts or runs. Its full compressed archive is large; it is removed
when extraction succeeds unless --keep-archive is supplied.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path, PurePosixPath
import shutil
import stat
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

METADATA_URL = "https://dl.google.com/android/repository/repository2-3.xml"
PACKAGE_PATH = "ndk;27.2.12479018"
URL_PREFIX = "https://dl.google.com/android/repository/android-ndk-r27c-linux"
SYSROOT_MEMBER_PREFIX = "android-ndk-r27c/toolchains/llvm/prebuilt/linux-x86_64/sysroot/"
USER_AGENT = "Xbox360Recomp-Termux-Builder/0.1"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def first_child_text(node: ET.Element, name: str) -> str | None:
    return next((child.text for child in node if local_name(child.tag) == name), None)


def select_archive(root: ET.Element) -> tuple[str, str]:
    for package in root.iter():
        if local_name(package.tag) != "remotePackage" or package.attrib.get("path") != PACKAGE_PATH:
            continue
        for archive in package.iter():
            if local_name(archive.tag) != "archive" or first_child_text(archive, "host-os") != "linux":
                continue
            complete = next((child for child in archive if local_name(child.tag) == "complete"), None)
            if complete is None:
                continue
            url = first_child_text(complete, "url")
            checksum = next((child for child in complete if local_name(child.tag) == "checksum"), None)
            if (url and checksum is not None and checksum.attrib.get("type") == "sha1"
                    and checksum.text and checksum.text.strip()):
                full_url = "https://dl.google.com/android/repository/" + url
                if not full_url.startswith(URL_PREFIX):
                    raise ValueError("Unexpected URL in Google's NDK repository metadata")
                return full_url, checksum.text.strip().lower()
    raise ValueError("Google metadata does not contain the Linux NDK r27c package")


def fetch_record(timeout: int = 90) -> tuple[str, str]:
    request = urllib.request.Request(METADATA_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return select_archive(ET.fromstring(response.read()))


def download_verified(url: str, expected_sha1: str, archive: Path) -> None:
    if archive.is_file():
        digest = hashlib.sha1()
        with archive.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() == expected_sha1:
            return
        archive.unlink()
    archive.parent.mkdir(parents=True, exist_ok=True)
    partial = archive.with_suffix(archive.suffix + ".part")
    digest = hashlib.sha1()
    received = 0
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as output:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                output.write(block)
                digest.update(block)
                received += len(block)
                if received and received % (64 * 1024 * 1024) < len(block):
                    print(f"Downloaded {received // (1024 * 1024)} MiB", flush=True)
        actual = digest.hexdigest()
        if actual != expected_sha1:
            raise ValueError(f"NDK archive SHA-1 mismatch: {actual} != {expected_sha1}")
        partial.replace(archive)
    finally:
        partial.unlink(missing_ok=True)


def sha1_file(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_sysroot(archive: Path, destination: Path) -> Path:
    destination = destination.expanduser().resolve()
    sysroot = destination / "sysroot"
    required = [sysroot / "usr/include/c++/v1", sysroot / "usr/lib/aarch64-linux-android/libc++_shared.so",
                sysroot / "usr/lib/aarch64-linux-android/33/libvulkan.so"]
    if all(path.exists() for path in required):
        return sysroot
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        members = [item for item in source.infolist() if item.filename.startswith(SYSROOT_MEMBER_PREFIX)]
        if not members:
            raise ValueError("NDK archive does not contain the expected Linux sysroot")
        for item in members:
            suffix = item.filename[len(SYSROOT_MEMBER_PREFIX):]
            parts = PurePosixPath(suffix).parts
            if (not parts or PurePosixPath(suffix).is_absolute()
                    or any(part in ("", ".", "..") for part in parts) or "\\" in suffix):
                raise ValueError(f"Unsafe path in NDK archive: {item.filename!r}")
            target = sysroot.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            mode = item.external_attr >> 16
            if stat.S_ISLNK(mode):
                link = source.read(item).decode("utf-8")
                if not link or Path(link).is_absolute() or "\\" in link:
                    raise ValueError(f"Unsafe symlink in NDK archive: {item.filename!r}")
                resolved = (target.parent / link).resolve()
                if not resolved.is_relative_to(sysroot):
                    raise ValueError(f"NDK symlink escapes sysroot: {item.filename!r}")
                if target.exists() or target.is_symlink():
                    target.unlink()
                target.symlink_to(link)
            elif item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                with source.open(item) as input_stream, target.open("wb") as output:
                    shutil.copyfileobj(input_stream, output, length=1024 * 1024)
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise ValueError("Extracted sysroot is incomplete; missing: " + ", ".join(missing))
    return sysroot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=Path, default=Path.home() / "android-ndk-r27c-termux",
                        help="Destination; resulting sysroot is <dest>/sysroot")
    parser.add_argument("--archive", type=Path, help="Use an existing NDK archive instead of downloading")
    parser.add_argument("--keep-archive", action="store_true", help="Keep the verified multi-gigabyte archive")
    args = parser.parse_args()
    archive = args.archive.expanduser().resolve() if args.archive else args.dest.expanduser().resolve().with_suffix(".zip")
    try:
        url, digest = fetch_record()
        print("Official NDK r27c URL:", url, flush=True)
        print("Checksum from Google metadata (SHA-1):", digest, flush=True)
        if args.archive is None:
            download_verified(url, digest, archive)
        else:
            if not archive.is_file():
                raise ValueError(f"Archive not found: {archive}")
            actual = sha1_file(archive)
            if actual != digest:
                raise ValueError(f"NDK archive SHA-1 mismatch: {actual} != {digest}")
        sysroot = extract_sysroot(archive, args.dest)
        print("Verified NDK sysroot:", sysroot, flush=True)
        if args.archive is None and not args.keep_archive:
            archive.unlink(missing_ok=True)
        return 0
    except (OSError, ValueError, urllib.error.URLError, zipfile.BadZipFile) as exc:
        print(f"NDK sysroot setup failed: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
