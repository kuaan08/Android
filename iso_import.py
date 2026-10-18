"""Bounded XDVDFS reader for extracted XISO and XGD1/2/3 images.

On-disk layout researched against antangelo/xdvdfs (MIT); original Python implementation.
"""
from pathlib import Path
import shutil
import struct

SECTOR = 2048
MAGIC = b"MICROSOFT*XBOX*MEDIA"
OFFSETS = (0, 405798912, 265879552, 34078720)


class Disc:
    def __init__(self, file):
        self.file = file
        self.size = file.seek(0, 2)
        self.base = None
        for offset in OFFSETS:
            if offset + 32 * SECTOR + SECTOR > self.size:
                continue
            header = self.read(offset + 32 * SECTOR, SECTOR)
            if header[:20] == MAGIC and header[-20:] == MAGIC:
                self.base = offset
                self.root_sector, self.root_size = struct.unpack_from("<II", header, 20)
                break
        if self.base is None:
            raise ValueError("No XDVDFS volume found. Expected an XISO or Xbox 360 XGD image.")

    def read(self, offset, count):
        if offset < 0 or count < 0 or offset + count > self.size:
            raise ValueError("ISO entry extends outside the image")
        self.file.seek(offset)
        data = self.file.read(count)
        if len(data) != count:
            raise ValueError("Truncated ISO")
        return data

    def entries(self):
        result, paths, directories = [], set(), set()
        pending = [(Path(), self.root_sector, self.root_size, 0)]
        while pending:
            parent, sector, size, depth = pending.pop()
            if depth > 64 or size > 64 * 1024 * 1024:
                raise ValueError("Invalid or excessive ISO directory tree")
            if (sector, size) in directories:
                raise ValueError("Cyclic ISO directory")
            directories.add((sector, size))
            table = self.read(self.base + sector * SECTOR, size)
            stack, visited = ([0] if size else []), set()
            while stack:
                pos = stack.pop()
                if pos in visited or pos + 14 > len(table):
                    raise ValueError("Invalid ISO directory node")
                visited.add(pos)
                left, right, start, length, attributes, count = struct.unpack_from("<HHIIBB", table, pos)
                if not count or pos + 14 + count > len(table):
                    raise ValueError("Invalid ISO filename length")
                name = table[pos + 14:pos + 14 + count].decode("ascii", errors="strict")
                if name in (".", "..") or any(c in name for c in '/\\:\x00') or any(ord(c) < 32 for c in name):
                    raise ValueError("Unsafe ISO filename")
                path = parent / name
                key = path.as_posix().lower()
                if key in paths:
                    raise ValueError("Duplicate ISO path")
                paths.add(key)
                if len(paths) > 200000:
                    raise ValueError("ISO contains too many entries")
                offset = self.base + start * SECTOR
                if offset + length > self.size:
                    raise ValueError("ISO file extends outside the image")
                is_dir = bool(attributes & 0x10)
                result.append((path, offset, length, is_dir))
                if is_dir and length:
                    pending.append((path, start, length, depth + 1))
                if right not in (0, 0xFFFF):
                    stack.append(right * 4)
                if left not in (0, 0xFFFF):
                    stack.append(left * 4)
        return result


def inspect_iso(path):
    with Path(path).open("rb") as f:
        disc = Disc(f)
        entries = disc.entries()
        xex = [p.as_posix() for p, _, _, d in entries if not d and p.suffix.lower() == ".xex"]
        return {"format": "XDVDFS", "partition_offset": disc.base, "entries": len(entries),
                "extracted_size": sum(n for _, _, n, d in entries if not d), "executables": xex}


def extract_iso(source, destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("Extraction destination already exists; choose a new directory")
    with Path(source).open("rb") as f:
        disc = Disc(f)
        entries = disc.entries()  # validate all metadata before writing any files
        total = sum(n for _, _, n, d in entries if not d)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(destination.parent).free < total + 64 * 1024 * 1024:
            raise ValueError("Not enough free space for ISO extraction")
        destination.mkdir()
        try:
            for index, (path, offset, length, is_dir) in enumerate(entries):
                target = destination / path
                if not target.resolve().is_relative_to(destination):
                    raise ValueError("Unsafe extraction path")
                if is_dir:
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                f.seek(offset)
                with target.open("xb") as out:
                    remaining = length
                    while remaining:
                        chunk = f.read(min(remaining, 1024 * 1024))
                        if not chunk:
                            raise ValueError("Truncated ISO payload")
                        out.write(chunk)
                        remaining -= len(chunk)
                print(f"Extracting ISO: {index + 1}/{len(entries)} {path}", flush=True)
        except BaseException:
            shutil.rmtree(destination)
            raise
    return destination


def find_xex(root):
    root = Path(root)
    files = list(root.rglob("*"))
    default = [p for p in files if p.is_file() and p.name.lower() == "default.xex"]
    if len(default) == 1:
        return default[0]
    candidates = [p for p in files if p.is_file() and p.suffix.lower() == ".xex"]
    if len(candidates) == 1:
        return candidates[0]
    raise ValueError("Choose a specific XEX: no unique default.xex was found")
