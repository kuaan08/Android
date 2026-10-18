#!/usr/bin/env python3
"""Xbox 360 Recomp: project management around the pinned ReXGlue SDK.

Copyright 2026 katakishi0. Apache-2.0. See NOTICE.txt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
import zipfile

# The portable Windows Python distribution uses an isolated _pth. Its sibling
# application modules are trusted payload files, not modules from the CWD.
sys.path.insert(0, str(Path(__file__).resolve().parent))

VERSION = "0.3.1"
SDK_VERSION = "0.10.0"
SDK_COMMIT = "f5337cdc947ff6d4c4196737e2c807a48f2a1fc2"
SDK_HASHES = {
    "win-amd64": "ad4485da853fbe932e9f5dbb643f9b5fe85dc73775ebbad4df6879fe6df0c11b",
    "linux-amd64": "0388edb3f8fb1444f1b0ad5d440cb02d9690ac20a76b04fd6b7dcc19f59328a6",
}
PROJECT_FILE = "xbo360-project.json"


class RecompError(Exception):
    pass


def host_platform() -> str:
    machine = platform.machine().lower()
    if machine not in ("amd64", "x86_64"):
        raise RecompError("This release supports Windows/Linux x64 hosts only.")
    if sys.platform == "win32":
        return "win-amd64"
    if sys.platform.startswith("linux"):
        return "linux-amd64"
    raise RecompError("This release supports Windows/Linux x64 hosts only.")


def cache_root() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache"))
    return base / "Xbox360Recomp"


def sdk_default() -> Path:
    bundled = Path(__file__).resolve().parent / "sdk"
    if (bundled / "bin").is_dir():
        return bundled
    return cache_root() / "sdk" / SDK_VERSION / host_platform()


def sdk_executable(prefix: Path) -> Path:
    return prefix / "bin" / ("rexglue.exe" if os.name == "nt" else "rexglue")


def check_sdk(prefix: Path) -> Path:
    exe = sdk_executable(prefix)
    if not exe.is_file():
        raise RecompError(f"ReXGlue not found at {exe}. Run install-sdk or choose an SDK prefix.")
    try:
        version = subprocess.check_output([str(exe), "--version"], text=True,
                                          stderr=subprocess.STDOUT, timeout=20).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise RecompError(f"Cannot start ReXGlue: {exc}") from exc
    if version != SDK_VERSION:
        raise RecompError(f"Expected ReXGlue {SDK_VERSION}, found {version!r}. SDK APIs differ.")
    return exe


def install_sdk(destination: Path | None = None) -> Path:
    host = host_platform()
    destination = (destination or sdk_default()).resolve()
    if destination.exists():
        check_sdk(destination)
        print(f"SDK already installed: {destination}", flush=True)
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    name = f"rexglue-sdk-{SDK_VERSION}-{host}.zip"
    url = f"https://github.com/rexglue/rexglue-sdk/releases/download/v{SDK_VERSION}/{name}"
    print(f"Downloading ReXGlue {SDK_VERSION} ({host})...", flush=True)
    with tempfile.TemporaryDirectory(prefix="sdk-download-", dir=destination.parent) as tmp:
        tmp = Path(tmp)
        archive = tmp / "sdk.zip"
        request = urllib.request.Request(url, headers={"User-Agent": "Xbox360Recomp/" + VERSION})
        digest = hashlib.sha256()
        with urllib.request.urlopen(request, timeout=60) as response, archive.open("wb") as out:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                out.write(chunk)
        if digest.hexdigest() != SDK_HASHES[host]:
            raise RecompError("SDK SHA-256 mismatch; installation aborted.")
        unpacked = tmp / "unpacked"
        unpacked.mkdir()
        with zipfile.ZipFile(archive) as z:
            for entry in z.infolist():
                target = (unpacked / entry.filename).resolve()
                if not target.is_relative_to(unpacked.resolve()) or "\\" in entry.filename:
                    raise RecompError("Unsafe path in SDK archive.")
                if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                    raise RecompError("Unexpected symbolic link in SDK archive.")
            z.extractall(unpacked)
        source = unpacked / host
        exe = sdk_executable(source)
        if os.name != "nt" and exe.exists():
            exe.chmod(0o755)
        check_sdk(source)
        source.rename(destination)
    print(f"SDK installed: {destination}", flush=True)
    return destination


def inspect_xex(path: Path) -> dict:
    """Validate the XEX2 header; decoding/decryption is delegated to ReXGlue."""
    size = path.stat().st_size
    with path.open("rb") as f:
        header = f.read(24)
        if len(header) != 24 or header[:4] != b"XEX2":
            raise RecompError("Expected an extracted Xbox 360 XEX2 executable (.xex).")
        magic, flags, pe_offset, reserved, security, count = struct.unpack(">4s5I", header)
        if count > 4096 or 24 + count * 8 > size:
            raise RecompError("Truncated or invalid XEX optional header table.")
        if pe_offset < 24 + count * 8 or pe_offset >= size:
            raise RecompError("XEX executable image offset is outside the file.")
        if security and (security < 24 + count * 8 or security >= size):
            raise RecompError("XEX security header offset is outside the file.")
        optional = [struct.unpack(">II", f.read(8)) for _ in range(count)]
    return {"format": "XEX2", "size": size, "module_flags": flags,
            "image_offset": pe_offset, "security_offset": security,
            "optional_header_count": count,
            "optional_headers": [{"key": f"0x{k:08X}", "value": v} for k, v in optional]}


def project_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", value):
        raise RecompError("Name must start with a letter and contain up to 64 letters, numbers or underscores.")
    # A normalized name makes SDK-generated target and manifest names predictable.
    if value != value.lower():
        raise RecompError("Use a lowercase project name, for example my_game.")
    return value


def run(args: list[str], cwd: Path, log: Path, env: dict | None = None) -> None:
    if env and not Path(args[0]).is_absolute():
        resolved = shutil.which(args[0], path=env.get("PATH"))
        if resolved:
            args = [resolved, *args[1:]]
    print("> " + subprocess.list2cmdline(args), flush=True)
    with log.open("a", encoding="utf-8") as output:
        output.write("> " + subprocess.list2cmdline(args) + "\n")
        output.flush()
        with subprocess.Popen(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                              errors="replace", env=env) as child:
            try:
                for line in child.stdout:
                    print(line.rstrip(), flush=True)
                    output.write(line)
                    output.flush()
                code = child.wait()
            except BaseException:
                child.terminate()
                child.wait()
                raise
    if code:
        raise RecompError(f"{Path(args[0]).name} failed (exit {code}). Full log: {log}")


def write_json(path: Path, value: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


def fix_manifest_paths(manifest: Path, xex: Path, game_root: Path) -> None:
    """SDK 0.10.0 lowercases host paths. Restore case for case-sensitive hosts."""
    text = manifest.read_text(encoding="utf-8")
    files: dict[str, list[Path]] = {}
    for p in game_root.rglob("*"):
        if p.is_file() and p.suffix.lower() == ".dll":
            key = os.path.relpath(p, manifest.parent).replace(os.sep, "/").lower()
            files.setdefault(key, []).append(p)
    section = ""
    lines = []
    for line in text.splitlines():
        if line.startswith("["):
            section = line.strip()
        key = line.partition("=")[0].strip()
        replacement = None
        if key == "game_root" and section == "[project]":
            replacement = game_root.as_posix()
        elif key == "file_path" and section == "[entrypoint]":
            replacement = xex.as_posix()
        elif key == "file_path" and section == "[[modules]]":
            old = tomllib.loads(line)["file_path"]
            candidates = files.get(old.lower(), [])
            if len(candidates) != 1:
                raise RecompError(f"Ambiguous or missing DLL path in manifest: {old}")
            replacement = candidates[0].as_posix()
        if replacement is not None:
            line = f"{key} = {json.dumps(replacement, ensure_ascii=False)}"
        lines.append(line)
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tomllib.loads(manifest.read_text(encoding="utf-8"))


def prepare(xex: Path, root: Path, name: str, sdk: Path, game_root: Path | None,
            scan_dlls: bool = True) -> dict:
    name = project_name(name)
    xex = xex.resolve(strict=True)
    details = inspect_xex(xex)
    game_root = (game_root or xex.parent).resolve(strict=True)
    root = root.resolve()
    if not game_root.is_dir() or not xex.is_relative_to(game_root):
        raise RecompError("The selected XEX must be inside the game data directory.")
    if root.is_relative_to(game_root) or game_root.is_relative_to(root):
        raise RecompError("Keep the project directory separate from the game data directory.")
    if root.exists() and any(root.iterdir()):
        raise RecompError("Project directory is not empty. Use codegen/build to resume it.")
    exe = check_sdk(sdk)
    root.mkdir(parents=True, exist_ok=True)
    print("Initializing Xbox 360 project...", flush=True)
    args = [str(exe), "init", "--project-name", name, "--project-root", str(root),
            "--xex-path", str(xex), "--game-root", str(game_root)]
    if scan_dlls:
        args.append("--scan-dll")
    run(args, root, root / "build.log")
    manifest = root / f"{name}_manifest.toml"
    fix_manifest_paths(manifest, xex, game_root)
    cmake = root / "CMakeLists.txt"
    source = cmake.read_text(encoding="utf-8")
    source = source.replace(f"rexglue_setup_target({name})",
                            f"rexglue_setup_target({name} GPU_PLUGINS xenos)")
    cmake.write_text(source, encoding="utf-8")
    # ReXApp otherwise loads game:\\default.xex regardless of the chosen input.
    app_header = root / "src" / f"{name}_app.h"
    source = app_header.read_text(encoding="utf-8")
    source = source.replace("#include <rex/rex_app.h>", """#include <rex/rex_app.h>
#include <rex/cvar.h>
#include <rex/system/gpu_plugin.h>
#include <stdexcept>

REXCVAR_DEFINE_STRING(xbo_renderer, "any", "GPU", "Xenos backend: any, d3d12, vulkan");""")
    source = source.replace("  // void OnPreSetup(rex::RuntimeConfig& config) override {}", """  void OnPreSetup(rex::RuntimeConfig& config) override {
    config.graphics = rex::system::LoadGpuPlugin("xenos", REXCVAR_GET(xbo_renderer));
    if (!config.graphics) throw std::runtime_error("Selected Xenos backend is unavailable; see runtime log.");
  }""")
    guest_path = "game:\\" + xex.relative_to(game_root).as_posix().replace("/", "\\")
    hook = "  void OnLoadXexImage(std::string& xex_image) override { xex_image = "
    hook += json.dumps(guest_path, ensure_ascii=True) + "; }"
    source = source.replace("  // void OnLoadXexImage(std::string& xex_image) override {}", hook)
    app_header.write_text(source, encoding="utf-8")
    state = {"schema": 1, "name": name, "sdk_version": SDK_VERSION,
             "sdk_commit": SDK_COMMIT, "sdk": str(sdk.resolve()), "manifest": manifest.name,
             "xex": str(xex), "game_root": str(game_root), "status": "prepared",
             "executable": None, "inspection": details}
    write_json(root / PROJECT_FILE, state)
    return state


def load_project(root: Path) -> dict:
    state = json.loads((root / PROJECT_FILE).read_text(encoding="utf-8"))
    if state.get("schema") != 1 or state.get("sdk_version") != SDK_VERSION:
        raise RecompError("Unsupported project schema or SDK version.")
    project_name(state["name"])
    manifest = (root / state["manifest"]).resolve()
    if not manifest.is_relative_to(root.resolve()) or not manifest.is_file():
        raise RecompError("Invalid project manifest path.")
    return state


def codegen(root: Path, sdk: Path | None = None, force: bool = False) -> dict:
    root = root.resolve()
    state = load_project(root)
    sdk = (sdk or Path(state["sdk"])).resolve()
    exe = check_sdk(sdk)
    state.update(status="generating", executable=None)
    write_json(root / PROJECT_FILE, state)
    print("Translating PowerPC to C++...", flush=True)
    try:
        command = [str(exe)] + (["--force"] if force else []) + ["codegen", str(root / state["manifest"])]
        if force:
            print("WARNING: Force skips analysis validation but does not repair code.", flush=True)
        run(command, root, root / "build.log")
    except BaseException:
        try:
            from analysis_hints import diagnose
            for branch in diagnose(root)["unresolved_branches"][:16]:
                print(f"Unresolved branch: {branch['source']} -> {branch['target']}. "
                      "Use Library > Function hints for a reviewed boundary; Force is optional.",
                      flush=True)
        except (ValueError, KeyError, OSError):
            pass
        state["status"] = "codegen_failed"
        write_json(root / PROJECT_FILE, state)
        raise
    state.update(status="generated", sdk=str(sdk))
    write_json(root / PROJECT_FILE, state)
    return state


def build(root: Path, sdk: Path | None = None, jobs: int = 0,
          configuration: str = "Release", force: bool = False) -> dict:
    root = root.resolve()
    state = load_project(root)
    sdk = (sdk or Path(state["sdk"])).resolve()
    check_sdk(sdk)
    import prerequisites
    env = prerequisites.build_environment()
    if not shutil.which("cmake", path=env.get("PATH")) or not shutil.which("ninja", path=env.get("PATH")):
        raise RecompError("CMake 3.25+ and Ninja must be on PATH. Windows also requires Visual Studio C++ and Clang 20+.")
    # Run explicit codegen before configure so generated source lists exist.
    state = codegen(root, sdk, force=force)
    preset = host_platform() + "-" + configuration.lower()
    env["PATH"] = str(sdk / "bin") + os.pathsep + env.get("PATH", "")
    state.update(status="building", executable=None)
    write_json(root / PROJECT_FILE, state)
    print("Compiling with CMake and Clang...", flush=True)
    try:
        run(["cmake", "--preset", preset, f"-DCMAKE_PREFIX_PATH={sdk.as_posix()}"], root,
            root / "build.log", env)
        args = ["cmake", "--build", "--preset", preset, "--parallel", str(jobs or os.cpu_count() or 1)]
        run(args, root, root / "build.log", env)
        binary_dir = root / "out" / "build" / preset
        exe_name = state["name"] + (".exe" if os.name == "nt" else "")
        candidates = [binary_dir / exe_name, binary_dir / configuration / exe_name]
        executable = next((p for p in candidates if p.is_file()), None)
        if executable is None:
            raise RecompError("Build returned success but the expected executable is missing.")
    except BaseException:
        state["status"] = "build_failed"
        write_json(root / PROJECT_FILE, state)
        raise
    state.update(status="built", executable=str(executable), configuration=configuration)
    write_json(root / PROJECT_FILE, state)
    print(f"Done: {executable}", flush=True)
    return state


def launch(root: Path, renderer: str | None = None, fullscreen: bool | None = None) -> int:
    root = root.resolve()
    state = load_project(root)
    settings_file = root / "launch-settings.json"
    settings = json.loads(settings_file.read_text()) if settings_file.is_file() else {}
    renderer = renderer or settings.get("renderer", "any")
    fullscreen = fullscreen if fullscreen is not None else settings.get("fullscreen", False)
    if renderer not in ("any", "d3d12", "vulkan") or not isinstance(fullscreen, bool):
        raise RecompError("Invalid per-game renderer/fullscreen setting")
    if state.get("status") != "built" or not state.get("executable"):
        raise RecompError("This project has no successfully built executable.")
    exe = Path(state["executable"])
    if not exe.is_file() or not exe.resolve().is_relative_to(root / "out"):
        raise RecompError("Built executable is missing or outside the project output directory.")
    env = os.environ.copy()
    # Keep SDK shared libraries available on Linux without copying its whole prefix.
    sdk = Path(state["sdk"])
    env["LD_LIBRARY_PATH"] = str(sdk / "lib") + os.pathsep + env.get("LD_LIBRARY_PATH", "")
    args = [str(exe), "--game_data_root", state["game_root"], "--gpu_plugin", "xenos",
            "--xbo_renderer", renderer, "--fullscreen" if fullscreen else "--no-fullscreen"]
    print("> " + subprocess.list2cmdline(args), flush=True)
    return subprocess.call(args, cwd=exe.parent, env=env)


def doctor(sdk: Path) -> bool:
    ok = True
    try:
        print(f"ReXGlue: {check_sdk(sdk)} ({SDK_VERSION})")
    except RecompError as exc:
        print(str(exc))
        ok = False
    import prerequisites
    detected = prerequisites.report()
    for tool in detected["tools"]:
        print(f"{tool['name']}: {tool['version'] or 'MISSING'}")
    print("Visual Studio: " + str(detected["visual_studio"] or "not found / not required on this host"))
    return ok and detected["desktop_ready"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Xbox 360 Recomp — ReXGlue project workbench")
    parser.add_argument("--version", action="version", version=VERSION)
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("install-sdk", help="Download and verify the pinned SDK")
    install.add_argument("--sdk", type=Path)
    inspect = commands.add_parser("inspect", help="Inspect an extracted XEX2 header")
    inspect.add_argument("input", type=Path)
    doc = commands.add_parser("doctor", help="Check SDK and native toolchain")
    doc.add_argument("--sdk", type=Path)
    tools_cmd = commands.add_parser("toolchain", help="Detect build prerequisites as JSON")
    installer = commands.add_parser("install-tools", help="Open an official prerequisite installer")
    installer.add_argument("tool", choices=["visual-studio", "clang", "cmake", "ninja", "java", "git"])
    installer.add_argument("--yes", action="store_true", required=True,
                           help="Confirm installation was requested by the user")
    update = commands.add_parser("update", help="Check releases and optionally download a verified update")
    update.add_argument("--download", action="store_true")
    update.add_argument("--directory", type=Path)
    android = commands.add_parser("android", help="Export an Android launcher or per-title native APK")
    android.add_argument("--project", type=Path)
    android.add_argument("--sdk-source", type=Path)
    android.add_argument("--ndk", type=Path)
    android.add_argument("--android-sdk", type=Path)
    android.add_argument("--jobs", type=int, default=2)
    android.add_argument("--runtime", action="store_true")
    setup_android = commands.add_parser("setup-android", help="Install pinned Android tools after explicit consent")
    setup_android.add_argument("--yes", action="store_true", required=True)
    prepare_cmd = commands.add_parser("prepare", help="Initialize a project without codegen")
    compile_cmd = commands.add_parser("recompile", help="Prepare, translate, and build")
    for p in (prepare_cmd, compile_cmd):
        p.add_argument("input", type=Path)
        p.add_argument("--project", required=True, type=Path)
        p.add_argument("--name", required=True)
        p.add_argument("--game-root", type=Path)
        p.add_argument("--sdk", type=Path)
        p.add_argument("--no-scan-dll", action="store_true")
    for p in (commands.add_parser("codegen"), commands.add_parser("build")):
        p.add_argument("project", type=Path)
        p.add_argument("--force", action="store_true", help="Generate despite analysis errors (experimental)")
        p.add_argument("--sdk", type=Path)
        if p.prog.endswith("build"):
            p.add_argument("--jobs", type=int, default=0)
            p.add_argument("--configuration", choices=["Release", "Debug", "RelWithDebInfo"], default="Release")
    compile_cmd.add_argument("--generate-only", action="store_true")
    compile_cmd.add_argument("--force", action="store_true", help="Generate despite analysis errors (experimental)")
    compile_cmd.add_argument("--jobs", type=int, default=0)
    known_cmd = commands.add_parser("suggest-hints", help="Suggest verified function boundaries for an exact XEX checksum")
    known_cmd.add_argument("project", type=Path)
    diagnose_cmd = commands.add_parser("diagnose", help="Inspect the last analysis errors for a prepared project")
    diagnose_cmd.add_argument("project", type=Path)
    hint_cmd = commands.add_parser("function-hint", help="Record a manually verified function boundary")
    hint_cmd.add_argument("project", type=Path)
    hint_cmd.add_argument("--address", required=True, help="0xXXXXXXXX entry point from disassembly")
    hint_cmd.add_argument("--size", required=True, type=int, help="Verified function size in bytes")
    hint_cmd.add_argument("--parent", type=lambda x: int(x, 0), help="Optional parent for discontiguous function chunk")
    play = commands.add_parser("run")
    play.add_argument("project", type=Path)
    play.add_argument("--renderer", choices=["any", "d3d12", "vulkan"])
    play.add_argument("--fullscreen", action="store_true", default=None)
    args = parser.parse_args(argv)
    try:
        sdk = getattr(args, "sdk", None)
        if args.command == "setup-android":
            if os.name != "nt":
                raise RecompError("Automatic Android tool setup currently supports Windows. Use sdkmanager on Linux.")
            import android_tools
            print("Installing Android tools with verified downloads...", flush=True)
            print("SDK: " + str(android_tools.ensure_sdk()), flush=True)
            print("JDK: " + str(android_tools.ensure_jdk()), flush=True)
        elif args.command == "toolchain":
            import prerequisites
            print(json.dumps(prerequisites.report()))
        elif args.command == "install-tools":
            import prerequisites
            prerequisites.install(args.tool)
        elif args.command == "update":
            import updates
            info = updates.release(VERSION, host_platform())
            print(json.dumps(info), flush=True)
            if args.download and not info["current"]:
                target = updates.download(info, args.directory or cache_root() / "updates" / info["version"])
                print(f"Update downloaded and verified: {target}", flush=True)
                print(f"Done: {target}", flush=True)
        elif args.command == "android":
            import android_build
            android_build.export(args.project, args.sdk_source, args.ndk, args.android_sdk,
                                 args.runtime, args.jobs)
        elif args.command == "suggest-hints":
            from analysis_hints import suggest_hints
            print(json.dumps(suggest_hints(args.project), indent=2))
        elif args.command == "diagnose":
            from analysis_hints import diagnose
            print(json.dumps(diagnose(args.project), indent=2))
        elif args.command == "function-hint":
            from analysis_hints import save_hint
            print(json.dumps(save_hint(args.project, args.address, args.size, args.parent), indent=2))
        elif args.command == "install-sdk":
            install_sdk(sdk)
        elif args.command == "inspect":
            if args.input.suffix.lower() in (".iso", ".xiso"):
                from iso_import import inspect_iso
                print(json.dumps(inspect_iso(args.input), indent=2))
            elif args.input.is_dir():
                from iso_import import find_xex
                print(json.dumps(inspect_xex(find_xex(args.input)), indent=2))
            else:
                print(json.dumps(inspect_xex(args.input), indent=2))
        elif args.command == "doctor":
            return 0 if doctor(sdk or sdk_default()) else 1
        elif args.command in ("prepare", "recompile"):
            sdk = (sdk or sdk_default()).resolve()
            check_sdk(sdk)  # fail before a potentially lengthy ISO extraction
            source = args.input
            game_root = args.game_root
            if source.suffix.lower() in (".iso", ".xiso"):
                from iso_import import extract_iso, find_xex
                # Keep original assets separate from generated project files.
                game_root = args.project.resolve().with_name(args.project.name + "_assets")
                extract_iso(source, game_root)
                source = find_xex(game_root)
            elif source.is_dir():
                from iso_import import find_xex
                game_root = source
                source = find_xex(source)
            prepare(source, args.project, args.name, sdk, game_root, not args.no_scan_dll)
            if args.command == "recompile":
                if args.generate_only:
                    codegen(args.project, sdk, force=args.force)
                else:
                    build(args.project, sdk, args.jobs, force=args.force)
            print(f"Project: {args.project.resolve()}", flush=True)
        elif args.command == "codegen":
            codegen(args.project, sdk, force=args.force)
        elif args.command == "build":
            if args.jobs < 0:
                raise RecompError("Jobs cannot be negative.")
            build(args.project, sdk, args.jobs, args.configuration, force=args.force)
        elif args.command == "run":
            return launch(args.project, args.renderer, args.fullscreen)
    except (RecompError, RuntimeError, OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        print(f"Error: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
