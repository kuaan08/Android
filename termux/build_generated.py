#!/usr/bin/env python3
"""Build a per-title ARM64 APK in Termux from the launcher's generated-source ZIP.

This is an experimental, user-run Termux workflow. It never invokes su/root and
never executes the XEX; the XEX is read as an input file by ReXGlue codegen and
is copied into the APK only as a relative runtime path, not as game data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import android_build  # noqa: E402


class BuildError(RuntimeError):
    pass


def run(args: list[str], cwd: Path, log: Path) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    rendered = subprocess.list2cmdline([str(a) for a in args])
    print("> " + rendered, flush=True)
    with log.open("a", encoding="utf-8") as output:
        output.write("> " + rendered + "\n")
        with subprocess.Popen([str(a) for a in args], cwd=cwd, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                              text=True, encoding="utf-8", errors="replace") as child:
            assert child.stdout is not None
            for line in child.stdout:
                print(line.rstrip(), flush=True)
                output.write(line)
                output.flush()
            code = child.wait()
    if code:
        raise BuildError(f"{Path(args[0]).name} failed (exit {code}); see {log}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_inside(path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve(strict=True)
    base = root.resolve(strict=True)
    if not resolved.is_relative_to(base) or resolved == base:
        raise BuildError(f"{label} escapes its selected directory")
    return resolved


def load_inputs(bundle: Path, game_root: Path):
    bundle = bundle.resolve(strict=True)
    game_root = game_root.resolve(strict=True)
    if not game_root.is_dir():
        raise BuildError("--game-root must be a directory containing the extracted game data")
    metadata_path = bundle / "xbo-game.json"
    project = bundle / "generated-project"
    if not metadata_path.is_file() or not project.is_dir():
        raise BuildError("Bundle must contain xbo-game.json and generated-project/")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f"Invalid xbo-game.json: {exc}") from exc

    rel = PurePosixPath(str(metadata.get("xex_path", "")))
    if not rel.parts or rel.is_absolute() or any(part in ("", ".", "..") for part in rel.parts):
        raise BuildError("xbo-game.json has an unsafe xex_path")
    xex = require_inside(game_root.joinpath(*rel.parts), game_root, "XEX path")
    if not xex.is_file() or sha256(xex) != metadata.get("sha256"):
        raise BuildError("The selected game folder does not match the XEX SHA-256 in xbo-game.json")
    with xex.open("rb") as stream:
        if stream.read(4) != b"XEX2":
            raise BuildError("The selected entrypoint is not an Xbox 360 XEX2 file")
    if any(p.is_file() and p.suffix.lower() == ".dll" for p in game_root.rglob("*")):
        raise BuildError("This prototype is single-XEX only; guest DLL integration is not implemented")

    manifests = sorted(project.glob("*_manifest.toml"))
    if len(manifests) != 1:
        raise BuildError("generated-project must contain exactly one *_manifest.toml")
    manifest_path = manifests[0]
    try:
        manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise BuildError(f"Invalid ReXGlue manifest: {exc}") from exc
    if manifest.get("modules"):
        raise BuildError("Guest DLL modules are not yet supported by the Android APK builder")
    project_name = str(manifest.get("project", {}).get("name", ""))
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", project_name):
        raise BuildError("Manifest project.name is not a safe Android target identifier")
    entry = str(manifest.get("entrypoint", {}).get("out_directory_path", ""))
    entry_path = PurePosixPath(entry)
    if (not entry_path.parts or entry_path.is_absolute() or
            any(part in ("", ".", "..") for part in entry_path.parts) or
            not re.fullmatch(r"[A-Za-z0-9_./-]+", entry)):
        raise BuildError("Manifest entrypoint.out_directory_path is unsafe or unsupported")
    entry_dir = project.joinpath(*entry_path.parts).resolve(strict=True)
    if not entry_dir.is_relative_to(project.resolve(strict=True)) or not (entry_dir / "sources.cmake").is_file():
        raise BuildError("Generated entrypoint sources.cmake is missing or outside the project")
    return bundle, game_root, project, manifest_path, manifest, project_name, entry, xex, rel.as_posix(), metadata


def toml_string(value: str) -> str:
    # JSON quoted strings are a compatible subset of TOML basic strings.
    return json.dumps(value, ensure_ascii=False)


def rewrite_manifest(manifest_path: Path, game_root: Path, xex: Path) -> None:
    lines = manifest_path.read_text(encoding="utf-8").splitlines()
    section = ""
    output = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            section = stripped
        key, sep, _ = stripped.partition("=")
        if sep and section == "[project]" and key.strip() == "game_root":
            line = "game_root = " + toml_string(game_root.as_posix())
        elif sep and section == "[entrypoint]" and key.strip() == "file_path":
            line = "file_path = " + toml_string(xex.as_posix())
        output.append(line)
    updated = "\n".join(output) + "\n"
    parsed = tomllib.loads(updated)
    if parsed.get("project", {}).get("game_root") != game_root.as_posix() or parsed.get("entrypoint", {}).get("file_path") != xex.as_posix():
        raise BuildError("Could not safely relocate the ReXGlue manifest paths")
    manifest_path.write_text(updated, encoding="utf-8")


def cpp_string(value: str) -> str:
    encoded = value.encode("utf-8")
    result = ['"']
    for byte in encoded:
        if byte == 0x22:
            result.append('\\"')
        elif byte == 0x5C:
            result.append('\\\\')
        elif 0x20 <= byte < 0x7F:
            result.append(chr(byte))
        else:
            result.append(f"\\{byte:03o}")
    result.append('"')
    return "".join(result)


def prepare_project(project: Path, manifest_path: Path, manifest: dict,
                    project_name: str, entry: str, game_root: Path, xex: Path,
                    relative_xex: str) -> None:
    app_header = project / "src" / f"{project_name}_app.h"
    if not app_header.is_file():
        raise BuildError(f"Generated app header is missing: {app_header}")
    code = app_header.read_text(encoding="utf-8")
    code = re.sub(r"\bPPCImageConfig\b", project_name + "_PPCImageConfig", code)
    guest_path = "game:\\" + relative_xex.replace("/", "\\")
    replacement = ("  void OnLoadXexImage(std::string& xex_image) override { xex_image = " +
                   cpp_string(guest_path) + "; }")
    hook = re.compile(r"(?m)^[ \t]*//[ \t]*void OnLoadXexImage\(std::string& xex_image\) override \{[ \t]*\}[ \t]*$")
    code, changed = hook.subn(lambda _match: replacement, code, count=1)
    if changed == 0:
        existing = re.compile(r"(?m)^[ \t]*void OnLoadXexImage\(std::string& xex_image\) override \{[^{}\r\n]*\}[ \t]*$")
        code, changed = existing.subn(lambda _match: replacement, code, count=1)
    if changed != 1:
        raise BuildError("Could not find the expected ReXGlue OnLoadXexImage hook")
    app_header.write_text(code, encoding="utf-8")

    cmake = f'''cmake_minimum_required(VERSION 3.25)
project(xbo_android LANGUAGES C CXX)
# The Termux toolchain compiles an Android target with native Termux Clang.
# Set this only after CMake has detected that compiler; setting it in the
# initial toolchain causes CMake to demand Google's x86_64-host NDK compiler.
set(ANDROID TRUE)
set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
add_link_options("-Wl,-z,max-page-size=16384" "-Wl,-z,common-page-size=16384")
set(REXGLUE_ENABLE_TRACY OFF CACHE BOOL "" FORCE)
set(REXGLUE_ENABLE_PERF_COUNTERS OFF CACHE BOOL "" FORCE)
set(REXGLUE_ENABLE_FIDELITYFX OFF CACHE BOOL "" FORCE)
set(REXGLUE_USE_D3D12 OFF CACHE BOOL "" FORCE)
set(REXGLUE_USE_VULKAN ON CACHE BOOL "" FORCE)
if(NOT DEFINED REXSDK_DIR)
  message(FATAL_ERROR "Pass -DREXSDK_DIR=<pinned ReXGlue source checkout>")
endif()
add_subdirectory("${{REXSDK_DIR}}" rexglue-sdk)
set(XBO_ENTRY_DIR "{entry}")
include("${{CMAKE_CURRENT_SOURCE_DIR}}/${{XBO_ENTRY_DIR}}/sources.cmake")
add_library(xbo_game SHARED src/main.cpp ${{GENERATED_SOURCES}})
target_include_directories(xbo_game PRIVATE . src "${{XBO_ENTRY_DIR}}")
target_link_libraries(xbo_game PRIVATE rex::runtime)
rexglue_configure_target(xbo_game)
'''
    (project / "CMakeLists.txt").write_text(cmake, encoding="utf-8")
    rewrite_manifest(manifest_path, game_root, xex)


def ensure_runtime_source(source: Path, log: Path) -> Path:
    revision = android_build.ANDROID_REVISION
    repository = android_build.ANDROID_REPO
    if not (source / ".git").exists():
        if source.exists() and any(source.iterdir()):
            raise BuildError(f"Runtime directory is not empty and has no Git checkout: {source}")
        source.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--filter=blob:none", "--no-checkout", repository, source], ROOT, log)
        run(["git", "-C", source, "checkout", "--detach", revision], ROOT, log)
    try:
        head = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BuildError(f"Cannot inspect the ReXGlue checkout: {exc}") from exc
    if head != revision:
        raise BuildError(f"ReXGlue checkout must be pinned to {revision}; found {head}")
    run(["git", "-C", source, "submodule", "update", "--init", "--recursive", "--depth", "1", "--jobs", "4"], ROOT, log)
    return source.resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True, help="Extracted root of the launcher ZIP")
    parser.add_argument("--game-root", type=Path, required=True, help="User's separate, extracted game data directory")
    parser.add_argument("--ndk-sysroot", type=Path, default=os.environ.get("ANDROID_NDK_SYSROOT"),
                        help="Android NDK sysroot; or set ANDROID_NDK_SYSROOT")
    parser.add_argument("--android-sdk", type=Path, default=os.environ.get("ANDROID_HOME"),
                        help="SDK folder with platforms/android-35/android.jar")
    parser.add_argument("--rexglue", type=Path,
                        default=Path.home() / ".cache/xbox360recomp/android-runtime",
                        help="Directory for the pinned ReXGlue checkout")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--native-only", action="store_true",
                        help="Stop after compiling libxbo_game.so; do not package an APK")
    args = parser.parse_args()
    if args.jobs < 1 or args.jobs > 64:
        parser.error("--jobs must be between 1 and 64")
    if args.ndk_sysroot is None:
        parser.error("Set ANDROID_NDK_SYSROOT or pass --ndk-sysroot")
    if args.android_sdk is None and not args.native_only:
        parser.error("Set ANDROID_HOME or pass --android-sdk")

    try:
        bundle, game_root, project, manifest_path, manifest, name, entry, xex, relative_xex, info = load_inputs(args.bundle, args.game_root)
        sysroot = args.ndk_sysroot.resolve(strict=True)
        if not (sysroot / "usr/include/c++/v1").is_dir():
            raise BuildError("NDK sysroot must include usr/include/c++/v1")
        shared = sysroot / "usr/lib/aarch64-linux-android/libc++_shared.so"
        if not shared.is_file():
            raise BuildError("NDK sysroot lacks usr/lib/aarch64-linux-android/libc++_shared.so")
        api_vulkan = sysroot / "usr/lib/aarch64-linux-android/33/libvulkan.so"
        if not api_vulkan.is_file():
            raise BuildError("NDK sysroot lacks the API 33 Vulkan loader import library")
        android_sdk = args.android_sdk.resolve(strict=True) if args.android_sdk is not None else None
        work = bundle / "termux-build"
        work.mkdir(parents=True, exist_ok=True)
        log = work / "build.log"
        prepare_project(project, manifest_path, manifest, name, entry, game_root, xex, relative_xex)
        source = ensure_runtime_source(args.rexglue.expanduser().resolve(), log)
        toolchain = ROOT / "termux/android-termux-toolchain.cmake"
        build_dir = work / "native"
        print("Configuring native Android ARM64 build with Termux Clang...", flush=True)
        run(["cmake", "-S", project, "-B", build_dir, "-G", "Ninja",
             f"-DCMAKE_TOOLCHAIN_FILE={toolchain}", f"-DANDROID_NDK_SYSROOT={sysroot}",
             "-DANDROID_ABI=arm64-v8a", "-DANDROID_PLATFORM=android-33", "-DANDROID_STL=c++_shared",
             "-DCMAKE_BUILD_TYPE=Release", f"-DREXSDK_DIR={source}"], ROOT, log)
        run(["cmake", "--build", build_dir, "--target", "xbo_game", "--parallel", str(args.jobs)], ROOT, log)
        game_libs = list(build_dir.rglob("libxbo_game.so"))
        runtime_lib = source / "out/linux-arm64/librexruntime.so"
        sdl_java = source / "thirdparty/sdl3/android-project/app/src/main/java/org/libsdl/app"
        if len(game_libs) != 1 or not runtime_lib.is_file() or not sdl_java.is_dir():
            raise BuildError("Build output is missing libxbo_game.so, librexruntime.so, or SDL Java sources")
        libs = [game_libs[0], runtime_lib, shared]
        license_files = [(p.relative_to(source).as_posix(), p) for p in source.rglob("*")
                         if p.is_file() and ".git" not in p.parts
                         and p.name.upper().startswith(("LICENSE", "COPYING")) and p.stat().st_size < 1024 * 1024]
        metadata = {
            "title": str(info.get("title") or name),
            "name": name,
            "package": "org.xbo360.game." + name,
            "native": True,
            "xex_path": relative_xex,
            "sha256": str(info["sha256"]),
            "runtime_revision": android_build.ANDROID_REVISION,
            "runtime_source": android_build.ANDROID_REPO,
        }
        if args.native_only:
            print(f"Native library: {game_libs[0]}", flush=True)
            print(f"Runtime library: {runtime_lib}", flush=True)
            return 0
        apk = android_build.package(work / "package", metadata, libs, sdl_java,
                                    android_sdk, license_files)
        print(f"APK: {apk}", flush=True)
        return 0
    except (BuildError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"Termux build failed safely: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
