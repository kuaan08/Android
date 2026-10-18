"""Project-specific ReXGlue diagnostics and manually verified function boundaries.

This module never guesses a function's size or changes original game assets.
"""
import json
import hashlib
import os
from pathlib import Path
import re
import tempfile
import tomllib

HINT_FILE = "xbo360-function-hints.toml"
ADDR = re.compile(r"0x[0-9a-fA-F]{8}\Z")
ERROR = re.compile(r"^\s*(0x[0-9a-fA-F]{8}) from (0x[0-9a-fA-F]{8}):\s*(.*?) - target not in any function\s*$", re.M)


def project_state(root):
    root = Path(root).resolve()
    state_file = root / "xbo360-project.json"
    if not state_file.is_file():
        raise ValueError("This is not a prepared Xbox360Recomp project.")
    state = json.loads(state_file.read_text(encoding="utf-8"))
    name = state.get("manifest", "")
    if not isinstance(name, str) or not name.endswith("_manifest.toml"):
        raise ValueError("Invalid project manifest name.")
    manifest = (root / name).resolve()
    if manifest.parent != root or not manifest.is_file():
        raise ValueError("Manifest is missing or outside the project directory.")
    return root, manifest, state


def diagnose(root):
    root, manifest, state = project_state(root)
    log = root / "build.log"
    data = log.read_text(encoding="utf-8", errors="replace")[-8_000_000:] if log.is_file() else ""
    branches = []
    seen = set()
    for target, source, instruction in ERROR.findall(data):
        pair = (source.upper(), target.upper())
        if pair not in seen:
            seen.add(pair)
            branches.append({"source": "0x" + source[2:].upper(),
                             "target": "0x" + target[2:].upper(),
                             "instruction": instruction})
    return {"project": str(root), "status": state.get("status"),
            "manifest": str(manifest), "unresolved_branches": branches,
            "warning": "A PowerPC b may be a tail call OR an intra-function jump. "
                       "Verify boundaries and size by disassembling the XEX."}



# Metadata only: obtained from disassembling a user-provided XEX. No game bytes
# or copyrighted executable contents are distributed with the workbench.
KNOWN_EXACT_BINARIES = {
    "9f718cac4cc7fb33ec7204e90d0901387f81e18c953eb1f90c40be5e2e3ff021": {
        "title": "Rise of the Tomb Raider",
        "title_id": "53510823",
        "media_id": "2427ED57",
        "version": "0.0.0.6",
        "hints": [{
            "address": "0x82C21240",
            "size": 112,
            "source_branch": "0x82C22B14",
            "evidence": ("PowerPC code ends with blr at 0x82C212AC; "
                         "next PDATA function begins at 0x82C212B0; "
                         "missing leaf function spans 0x82C21240..0x82C212B0."),
        }],
    },
}


def suggest_hints(root):
    """Suggest existing evidence-backed boundaries ONLY for exact matching XEX bytes.

    This never writes anything. GUI confirmation and save_hint are separate actions.
    """
    root, manifest, state = project_state(root)
    xex_value = state.get("xex")
    if not isinstance(xex_value, str) or not xex_value:
        raise ValueError("Project executable path missing; no verified hints available.")
    xex = Path(xex_value)
    if not xex.is_file() or xex.suffix.lower() != ".xex":
        raise ValueError("Original XEX is missing or moved.")
    digest = hashlib.sha256()
    with xex.open("rb") as file:
        if file.read(4) != b"XEX2":
            raise ValueError("Project executable is not a valid XEX2.")
        file.seek(0)
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    value = digest.hexdigest()
    known = KNOWN_EXACT_BINARIES.get(value)
    return {
        "project": str(root),
        "matching_revision": bool(known),
        "title": known["title"] if known else None,
        "hints": known["hints"] if known else [],
        "warning": ("Hints match the exact executable checksum and only address analysis "
                    "boundaries; they do not establish gameplay compatibility. "
                    "Select a hint and explicitly save it before codegen."),
    }

def atomic_write(path, text):
    fd, tmp = tempfile.mkstemp(prefix=".xbo360-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def save_hint(root, address, size, parent=None):
    root, manifest, state = project_state(root)
    if not isinstance(address, str) or not ADDR.fullmatch(address):
        raise ValueError("Address must have the form 0xXXXXXXXX.")
    addr = int(address, 16)
    if addr % 4 or type(size) is not int or size < 4 or size > 1048576 or size % 4:
        raise ValueError("Address must be aligned; size must be a verified multiple of 4 bytes (4..1048576).")
    if parent is not None and (type(parent) is not int or parent < 0 or parent > 0xFFFFFFFF or parent % 4 or parent == addr):
        raise ValueError("Parent function address is invalid.")
    source = manifest.read_text(encoding="utf-8")
    parsed = tomllib.loads(source)
    entry = parsed.get("entrypoint")
    if not isinstance(entry, dict):
        raise ValueError("Missing [entrypoint].")
    includes = entry.get("includes", [])
    if not isinstance(includes, list) or any(not isinstance(x, str) for x in includes):
        raise ValueError("Invalid entrypoint.includes.")
    revised = source
    if HINT_FILE not in includes:
        lines = source.splitlines()
        pos = next((i for i, line in enumerate(lines) if line.strip() == "[entrypoint]"), None)
        if pos is None:
            raise ValueError("Missing [entrypoint] header.")
        end = next((i for i in range(pos + 1, len(lines)) if lines[i].strip().startswith("[")), len(lines))
        matches = [i for i in range(pos + 1, end) if re.match(r"\s*includes\s*=", lines[i])]
        if len(matches) > 1:
            raise ValueError("Duplicate includes; refusing to edit.")
        if matches and not re.fullmatch(r"\s*includes\s*=\s*\[[^\[\]\n]*\]\s*(?:#.*)?", lines[matches[0]]):
            raise ValueError("Multi-line includes require manual editing.")
        new_include = "includes = " + json.dumps(includes + [HINT_FILE])
        if matches:
            lines[matches[0]] = new_include
        else:
            lines.insert(end, new_include)
        revised = "\n".join(lines) + "\n"
        if HINT_FILE not in tomllib.loads(revised)["entrypoint"]["includes"]:
            raise ValueError("Invalid patched manifest.")
    hints = root / HINT_FILE
    existing = tomllib.loads(hints.read_text(encoding="utf-8")) if hints.is_file() else {}
    if set(existing) - {"functions"}:
        raise ValueError("Hints file has custom sections; edit it manually.")
    functions = existing.get("functions", {})
    if not isinstance(functions, dict):
        raise ValueError("Invalid function hints.")
    entries = {}
    for key, value in functions.items():
        if not ADDR.fullmatch(key) or not isinstance(value, dict) or set(value) - {"size", "parent"}:
            raise ValueError("Existing function hints contain custom fields; edit manually.")
        entries[int(key, 16)] = value
    proposed = {"size": size}
    if parent is not None:
        proposed["parent"] = parent
    if addr in entries and entries[addr] != proposed:
        raise ValueError("Existing hint differs. Review the file before replacing it.")
    entries[addr] = proposed
    text = "# Explicit function boundaries. Do not guess sizes from logs.\n[functions]\n"
    for address_int, config in sorted(entries.items()):
        if type(config.get("size")) is not int or config["size"] < 4 or config["size"] % 4:
            raise ValueError("Invalid existing hint size.")
        body = f"size = {config['size']}"
        if "parent" in config:
            body += f", parent = {config['parent']}"
        text += f'"0x{address_int:08X}" = {{ {body} }}\n'
    tomllib.loads(text)
    atomic_write(hints, text)
    if revised != source:
        atomic_write(manifest, revised)
    return {"address": f"0x{addr:08X}", "size": size,
            "parent": parent, "hints": str(hints), "manifest": str(manifest)}
