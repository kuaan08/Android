"""Build the Android library/menu APK and per-title ARM64 exports.

Android uses a separate pinned ReXGlue fork and its matching host codegen;
the desktop SDK's generated ABI is never mixed with this runtime.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile
from xml.sax.saxutils import quoteattr

from xbo360 import cache_root, load_project, run, fix_manifest_paths, write_json

HERE = Path(__file__).resolve().parent
ANDROID_REPO = "https://github.com/AlanConstantino/rexglue-skate3-android.git"
ANDROID_REVISION = "8dd8b369ba2770259776472b981bcecd0dcc11f0"


def latest(directory):
    return max((p for p in directory.glob("*") if p.is_dir()),
               key=lambda p: tuple(map(int, re.findall(r"\d+", p.name))), default=None)


def tools(sdk=None):
    import android_tools
    sdk = Path(sdk or os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or android_tools.SDK).resolve()
    bt = sdk / "build-tools/35.0.0"
    if not bt.is_dir():
        bt = latest(sdk / "build-tools")
    android = sdk / "platforms/android-35/android.jar"
    if not bt or not android.is_file():
        raise ValueError("Install Android SDK platform 35 and build-tools 35, or choose the SDK folder in Settings.")
    suffix = ".exe" if os.name == "nt" else ""
    java_home = Path(os.environ.get("JAVA_HOME", ""))
    fallback = android_tools.JDK
    found = {}
    for name in ("java", "javac", "keytool"):
        p = java_home / "bin" / (name + suffix)
        if not p.is_file():
            p = fallback / "bin" / (name + suffix)
        if not p.is_file():
            p = Path(shutil.which(name) or "__missing__")
        found[name] = p
    found.update(aapt2=bt / ("aapt2" + suffix), zipalign=bt / ("zipalign" + suffix),
                 d8=bt / "lib/d8.jar", apksigner=bt / "lib/apksigner.jar", android=android)
    if not all(p.is_file() for p in found.values()):
        raise ValueError("Android packaging requires a full JDK 17 and SDK aapt2, D8, zipalign and apksigner.")
    return sdk, found


def ensure_source(source, env, log):
    if source is None:
        source = cache_root() / "android/runtime-src"
        if not (source / ".git").exists():
            source.parent.mkdir(parents=True, exist_ok=True)
            run(["git", "init", str(source)], HERE, log, env)
            run(["git", "-C", str(source), "remote", "add", "origin", ANDROID_REPO], HERE, log, env)
        head = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], capture_output=True, text=True, env=env)
        if head.returncode or head.stdout.strip() != ANDROID_REVISION:
            run(["git", "-C", str(source), "fetch", "--depth", "1", "origin", ANDROID_REVISION], HERE, log, env)
            run(["git", "-C", str(source), "checkout", "--detach", "FETCH_HEAD"], HERE, log, env)
    source = source.resolve()
    head = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True, env=env).strip()
    if head != ANDROID_REVISION:
        raise ValueError(f"Android runtime must be pinned to {ANDROID_REVISION}; found {head}")
    run(["git", "-C", str(source), "submodule", "update", "--init", "--recursive", "--depth", "1", "--jobs", "4"], HERE, log, env)
    return source


def native_project(project, source, ndk, env, jobs, log):
    state = load_project(project)
    if jobs < 1:
        jobs = max(1, os.cpu_count() or 1)
    host_build = cache_root() / "android/host-tools"
    host_build.parent.mkdir(parents=True, exist_ok=True)
    host_options = host_build.parent / "host-options.cmake"
    # The Android fork's standalone host preset omits the SIMD baseline used
    # by downstream applications. Its memory.cpp uses SSSE3 unconditionally.
    # Propagate the baseline from rexcore to SDK consumers; do not rebuild unrelated dependencies
    # with a different CPU target or modify the pinned source checkout.
    host_options.write_text('''if(CMAKE_SYSTEM_PROCESSOR MATCHES "AMD64|x86_64")
  cmake_language(DEFER CALL target_compile_options rexcore PUBLIC -march=x86-64-v2)
endif()
''')
    cc = "clang" if os.name == "nt" else "clang-20"
    cxx = "clang++" if os.name == "nt" else "clang++-20"
    host_cli = source / "out" / ("win-amd64" if os.name == "nt" else "linux-amd64") / ("rexglue.exe" if os.name == "nt" else "rexglue")
    if not host_cli.is_file():
        print("Building matching Android SDK host code generator...", flush=True)
        run(["cmake", "-S", str(source), "-B", str(host_build), "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
             f"-DCMAKE_C_COMPILER={cc}", f"-DCMAKE_CXX_COMPILER={cxx}", "-DREXGLUE_ENABLE_TRACY=OFF",
             "-DREXGLUE_ENABLE_PERF_COUNTERS=OFF", "-DREXGLUE_ENABLE_FIDELITYFX=OFF",
             f"-DCMAKE_PROJECT_ReXGlue_INCLUDE={host_options.as_posix()}"], HERE, log, env)
        run(["cmake", "--build", str(host_build), "--target", "rexglue", "--parallel", str(jobs)], HERE, log, env)
    work = project / "android-export"
    generated = work / "native"
    name = state["name"]
    if not (generated / f"{name}_manifest.toml").exists():
        generated.mkdir(parents=True, exist_ok=True)
        run([str(host_cli), "init", "--project-name", name, "--project-root", str(generated),
             "--xex-path", state["xex"], "--game-root", state["game_root"], "--scan-dll"], HERE, log, env)
        fix_manifest_paths(generated / f"{name}_manifest.toml", Path(state["xex"]), Path(state["game_root"]))
    manifest = generated / f"{name}_manifest.toml"
    run([str(host_cli), "codegen", str(manifest)], generated, log, env)
    import tomllib
    config = tomllib.loads(manifest.read_text())
    if config.get("modules"):
        raise ValueError("Android guest DLL packaging needs per-module integration; this export currently supports single-XEX titles only.")
    entry = config["entrypoint"]["out_directory_path"]
    app_header = generated / "src" / f"{name}_app.h"
    code = app_header.read_text()
    code = re.sub(r"\bPPCImageConfig\b", name + "_PPCImageConfig", code)
    xex_rel = Path(state["xex"]).relative_to(state["game_root"]).as_posix().replace("/", "\\")
    code = code.replace("  // void OnLoadXexImage(std::string& xex_image) override {}",
                        "  void OnLoadXexImage(std::string& xex_image) override { xex_image = " + json.dumps("game:\\" + xex_rel) + "; }")
    app_header.write_text(code)
    cmake = f'''cmake_minimum_required(VERSION 3.25)
project(xbo_android LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 23)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
add_link_options("-Wl,-z,max-page-size=16384" "-Wl,-z,common-page-size=16384")
set(REXGLUE_ENABLE_TRACY OFF CACHE BOOL "" FORCE)
set(REXGLUE_ENABLE_PERF_COUNTERS OFF CACHE BOOL "" FORCE)
set(REXGLUE_ENABLE_FIDELITYFX OFF CACHE BOOL "" FORCE)
set(REXGLUE_USE_D3D12 OFF CACHE BOOL "" FORCE)
set(REXGLUE_USE_VULKAN ON CACHE BOOL "" FORCE)
add_subdirectory("${{REXSDK_DIR}}" rexglue-sdk)
include({entry}/sources.cmake)
add_library(xbo_game SHARED src/main.cpp ${{GENERATED_SOURCES}})
target_include_directories(xbo_game PRIVATE . src {entry})
target_link_libraries(xbo_game PRIVATE rex::runtime)
rexglue_configure_target(xbo_game)
'''
    (generated / "CMakeLists.txt").write_text(cmake)
    build_dir = work / "build"
    print("Compiling Android ARM64 runtime and game...", flush=True)
    run(["cmake", "-S", str(generated), "-B", str(build_dir), "-G", "Ninja",
         f"-DCMAKE_TOOLCHAIN_FILE={ndk.as_posix()}/build/cmake/android.toolchain.cmake",
         "-DANDROID_ABI=arm64-v8a", "-DANDROID_PLATFORM=android-33", "-DANDROID_STL=c++_shared",
         "-DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON", "-DCMAKE_BUILD_TYPE=Release",
         f"-DREXSDK_DIR={source.as_posix()}"], HERE, log, env)
    run(["cmake", "--build", str(build_dir), "--target", "xbo_game", "--parallel", str(jobs)], HERE, log, env)
    libs = list(build_dir.rglob("libxbo_game.so"))
    runtime = list((source / "out").glob("linux-arm64/librexruntime.so"))
    if not libs or not runtime:
        raise ValueError("Android build did not produce the expected native libraries")
    shared = next((ndk / "toolchains/llvm/prebuilt").glob("*/sysroot/usr/lib/aarch64-linux-android/libc++_shared.so"), None)
    if shared is None:
        raise ValueError("NDK libc++_shared.so is missing")
    return libs + runtime + [shared], source / "thirdparty/sdl3/android-project/app/src/main/java/org/libsdl/app"


def native_codegen_tools(source, ndk, env, jobs, log):
    """Build the optional in-launcher, single-XEX C++ generation library."""
    if jobs < 1:
        jobs = max(1, os.cpu_count() or 1)
    patcher = HERE / "android/ondevice/patch_rexglue_cmake.py"
    run([sys.executable, str(patcher), str(source)], HERE, log, env)
    build_dir = cache_root() / "android/ondevice-codegen-build"
    build_dir.parent.mkdir(parents=True, exist_ok=True)
    cmake_args = [
        "cmake", "-S", str(source), "-B", str(build_dir), "-G", "Ninja",
        f"-DCMAKE_TOOLCHAIN_FILE={ndk.as_posix()}/build/cmake/android.toolchain.cmake",
        "-DANDROID_ABI=arm64-v8a", "-DANDROID_PLATFORM=android-33",
        "-DANDROID_STL=c++_shared", "-DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON",
        "-DCMAKE_SHARED_LINKER_FLAGS=-Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384",
        "-DREXGLUE_ENABLE_TRACY=OFF", "-DREXGLUE_ENABLE_PERF_COUNTERS=OFF",
        "-DREXGLUE_ENABLE_FIDELITYFX=OFF", "-DREXGLUE_USE_D3D12=OFF",
        "-DREXGLUE_USE_VULKAN=ON",
        f"-DXBO360_ANDROID_CODEGEN_JNI_SOURCE={(HERE / 'android/ondevice/codegen_jni.cpp').as_posix()}",
        "-DCMAKE_BUILD_TYPE=Release",
    ]
    run(cmake_args, HERE, log, env)
    run(["cmake", "--build", str(build_dir), "--target", "xbo360_codegen_jni",
         "--parallel", str(jobs)], HERE, log, env)

    jni_libs = list((source / "out").glob("linux-arm64/libxbo360_codegen_jni.so"))
    runtime_libs = list((source / "out").glob("linux-arm64/librexruntime.so"))
    shared = next((ndk / "toolchains/llvm/prebuilt").glob(
        "*/sysroot/usr/lib/aarch64-linux-android/libc++_shared.so"), None)
    if len(jni_libs) != 1 or len(runtime_libs) != 1 or shared is None:
        raise ValueError("Android JNI codegen build did not produce the expected native libraries")
    return [jni_libs[0], runtime_libs[0], shared]


def package(work, metadata, libs, sdl_java, android_sdk, license_files=()):
    _, t = tools(android_sdk)
    work.mkdir(parents=True, exist_ok=True)
    log = work / "package.log"
    cmd = lambda args: run([str(a) for a in args], HERE, log)
    classes, dex = work / "classes", work / "dex"
    for directory in (classes, dex):
        if directory.exists():
            shutil.rmtree(directory)
    classes.mkdir(exist_ok=True); dex.mkdir(exist_ok=True)
    sources = [HERE / "android/LauncherActivity.java", HERE / "android/IsoReader.java",
               HERE / "android/CodegenBridge.java"]
    game_runtime = any(lib.name == "libxbo_game.so" for lib in libs)
    if game_runtime:
        sources += [HERE / "android/GameActivity.java"] + list(sdl_java.glob("*.java"))
    cmd([t["javac"], "-encoding", "UTF-8", "-source", "8", "-target", "8", "-classpath", t["android"], "-d", classes, *sources])
    class_files = sorted(classes.rglob("*.class"))
    # A single JAR avoids Windows' argument-length limit and D8 response-file
    # quoting differences, including paths with spaces and '$' inner classes.
    class_jar = work / "launcher.jar"
    with zipfile.ZipFile(class_jar, "w") as jar:
        for p in class_files:
            jar.write(p, p.relative_to(classes).as_posix())
    cmd([t["java"], "-cp", t["d8"], "com.android.tools.r8.D8", "--min-api", "33", "--lib", t["android"], "--output", dex, class_jar])
    game_activity = ('<activity android:name="org.xbo360.app.GameActivity" android:exported="false" android:process=":game" android:hardwareAccelerated="true" android:configChanges="orientation|keyboardHidden|keyboard|screenSize|smallestScreenSize|screenLayout|uiMode|navigation|density"/>' if game_runtime else '')
    manifest = work / "AndroidManifest.xml"
    manifest.write_text(f'''<manifest xmlns:android="http://schemas.android.com/apk/res/android" package={quoteattr(metadata['package'])} android:versionCode="301" android:versionName="0.3.1">
<uses-sdk android:minSdkVersion="33" android:targetSdkVersion="35"/>
<uses-permission android:name="android.permission.INTERNET"/>
<uses-feature android:name="android.hardware.gamepad" android:required="false"/>
<uses-feature android:name="android.hardware.vulkan.level" android:version="1" android:required="false"/>
<application android:label={quoteattr(metadata['title'])} android:theme="@android:style/Theme.Material.NoActionBar" android:allowBackup="false" android:extractNativeLibs="true" android:usesCleartextTraffic="false">
<activity android:name="org.xbo360.app.LauncherActivity" android:exported="true" android:configChanges="orientation|screenSize"><intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter></activity>{game_activity}</application></manifest>''')
    unsigned, aligned, output = work / "unsigned.apk", work / "aligned.apk", work / ("Xbox360Recomp-Android.apk" if not metadata["native"] else metadata["name"] + ".apk")
    cmd([t["aapt2"], "link", "-I", t["android"], "--manifest", manifest, "-o", unsigned])
    with zipfile.ZipFile(unsigned, "a") as z:
        for p in dex.glob("*.dex"):
            z.write(p, p.name, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("assets/project.json", json.dumps(metadata), compress_type=zipfile.ZIP_DEFLATED)
        for lib in libs:
            z.write(lib, "lib/arm64-v8a/" + lib.name, compress_type=zipfile.ZIP_STORED)
        for p in [HERE / "LICENSE.txt", HERE / "NOTICE.txt", HERE / "ci/licenses/ReXGlue-BSD-3-Clause.txt"]:
            z.write(p, "assets/licenses/" + p.name)
        for relative, p in license_files:
            z.write(p, "assets/licenses/android-runtime/" + relative, compress_type=zipfile.ZIP_DEFLATED)
    cmd([t["zipalign"], "-P", "16", "-f", "4", unsigned, aligned])
    key = Path(os.environ.get("XBO_ANDROID_KEYSTORE", cache_root() / "android/debug.keystore"))
    if not key.is_file():
        key.parent.mkdir(parents=True, exist_ok=True)
        cmd([t["keytool"], "-genkeypair", "-noprompt", "-keystore", key, "-storepass", "android", "-keypass", "android", "-alias", "androiddebugkey", "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000", "-dname", "CN=Xbox360Recomp Debug,O=Android,C=US"])
    cmd([t["java"], "-jar", t["apksigner"], "sign", "--ks", key, "--ks-pass", "pass:android", "--out", output, aligned])
    cmd([t["java"], "-jar", t["apksigner"], "verify", "--verbose", output])
    print(f"Done: {output}", flush=True)
    return output


def export(project=None, source=None, ndk=None, sdk=None, runtime=False,
           ondevice_codegen=False, jobs=2):
    import prerequisites
    import android_tools
    env = prerequisites.build_environment()
    work = (project.resolve() / "android-export") if project else HERE / "dist/android-launcher"
    work.mkdir(parents=True, exist_ok=True)
    metadata = {"title": "Xbox 360 Recomp", "name": "launcher", "package": "org.xbo360.launcher",
                "native": False, "xex_path": "", "sha256": ""}
    libs, java, license_files = [], None, []
    if runtime and ondevice_codegen:
        raise ValueError("Choose either a per-title runtime APK or the launcher codegen library, not both")
    if runtime:
        if project is None:
            raise ValueError("Native APK export requires a prepared project")
        state = load_project(project)
        sdk, _ = tools(sdk)
        ndk = Path(ndk or os.environ.get("ANDROID_NDK_ROOT") or sdk / "ndk/27.2.12479018").resolve()
        if not (ndk / "build/cmake/android.toolchain.cmake").is_file():
            raise ValueError("Install Android NDK r27c (27.2.12479018) or select its directory")
        source = ensure_source(source, env, work / "build.log")
        libs, java = native_project(project.resolve(), source, ndk, env, jobs, work / "build.log")
        license_files = [(p.relative_to(source).as_posix(), p) for p in source.rglob("*")
                         if p.is_file() and ".git" not in p.parts
                         and p.name.upper().startswith(("LICENSE", "COPYING")) and p.stat().st_size < 1024 * 1024]
        xex = Path(state["xex"])
        metadata.update(title=state["name"], name=state["name"], package="org.xbo360.game." + state["name"],
                        native=True, xex_path=xex.relative_to(state["game_root"]).as_posix(),
                        sha256=hashlib.sha256(xex.read_bytes()).hexdigest(), runtime_revision=ANDROID_REVISION,
                        runtime_source=ANDROID_REPO)
    elif ondevice_codegen:
        sdk, _ = tools(sdk)
        ndk = Path(ndk or os.environ.get("ANDROID_NDK_ROOT") or sdk / "ndk/27.2.12479018").resolve()
        if not (ndk / "build/cmake/android.toolchain.cmake").is_file():
            raise ValueError("Install Android NDK r27c (27.2.12479018) or select its directory")
        source = ensure_source(source, env, work / "build.log")
        libs = native_codegen_tools(source, ndk, env, jobs, work / "build.log")
        license_files = [(p.relative_to(source).as_posix(), p) for p in source.rglob("*")
                         if p.is_file() and ".git" not in p.parts
                         and p.name.upper().startswith(("LICENSE", "COPYING")) and p.stat().st_size < 1024 * 1024]
    output = package(work, metadata, libs, java, sdk, license_files)
    if project:
        write_json(work / "export.json", {"apk": str(output), "native": bool(metadata["native"]),
                                           "ondevice_codegen": any(lib.name == "libxbo360_codegen_jni.so" for lib in libs),
                                           "metadata": metadata})
    return output
