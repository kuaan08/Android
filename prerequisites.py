"""Detect Windows build tools and start user-requested official installers."""
import json
import os
from pathlib import Path
import shutil
import subprocess

VS_COMPONENTS = ["Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                 "Microsoft.VisualStudio.Component.VC.Llvm.Clang",
                 "Microsoft.VisualStudio.Component.VC.CMake.Project"]
PACKAGES = {"visual-studio": "Microsoft.VisualStudio.2022.BuildTools",
            "clang": "LLVM.LLVM", "cmake": "Kitware.CMake", "ninja": "Ninja-build.Ninja",
            "java": "Microsoft.OpenJDK.17", "git": "Git.Git"}


def vs_installation():
    if os.name != "nt":
        return None
    vswhere = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft Visual Studio/Installer/vswhere.exe"
    if not vswhere.is_file():
        return None
    p = subprocess.run([str(vswhere), "-latest", "-products", "*", "-requires",
                        VS_COMPONENTS[0], "-property", "installationPath"], capture_output=True,
                       text=True, timeout=20)
    value = p.stdout.strip()
    return Path(value) if p.returncode == 0 and value else None


def build_environment():
    """Capture vcvars without making users start the GUI from a developer shell."""
    env = os.environ.copy()
    if os.name != "nt":
        return env
    vs = vs_installation()
    if vs:
        batch = vs / "VC/Auxiliary/Build/vcvars64.bat"
        # This is a discovered installation path, not arbitrary user command text.
        if batch.is_file() and not any(c in str(batch) for c in ('"', '&', '|', '%', '\n')):
            cmd = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/cmd.exe"
            command = f'"{cmd}" /d /s /c ""{batch}" >nul && set"'
            result = subprocess.run(command, shell=False, capture_output=True,
                                    text=True, errors="replace", timeout=45)
            if result.returncode:
                raise RuntimeError("Visual Studio environment initialization failed.")
            env.update(line.split("=", 1) for line in result.stdout.splitlines()
                       if "=" in line and not line.startswith("="))
        candidates = [vs / "VC/Tools/Llvm/x64/bin", vs / "VC/Tools/Llvm/bin",
                      vs / "Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin",
                      vs / "Common7/IDE/CommonExtensions/Microsoft/CMake/Ninja"]
    else:
        candidates = []
    pf = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
    # Standalone LLVM may be newer than the copy supplied by VS.
    candidates = [pf / "LLVM/bin", pf / "CMake/bin"] + candidates
    env["PATH"] = os.pathsep.join(str(p) for p in candidates if p.is_dir()) + os.pathsep + env.get("PATH", "")
    return env


def report():
    env = build_environment()
    tools = []
    for name in ("cmake", "ninja", "clang" if os.name == "nt" else "clang-20",
                 "clang++" if os.name == "nt" else "clang++-20", "java", "git"):
        path = shutil.which(name, path=env.get("PATH"))
        version = ""
        if path:
            try:
                proc = subprocess.run([path, "-version" if name == "java" else "--version"],
                                      capture_output=True, text=True, timeout=10, env=env)
                version = (proc.stdout or proc.stderr).splitlines()[0]
            except (OSError, subprocess.SubprocessError, IndexError):
                pass
        supported = bool(path)
        if name in ("clang", "clang++", "clang-20", "clang++-20") and version:
            import re
            match = re.search(r"version\s+(\d+)", version)
            supported = bool(match and int(match[1]) >= 20)
        if name == "cmake" and version:
            import re
            match = re.search(r"(\d+)\.(\d+)", version)
            supported = bool(match and tuple(map(int, match.groups())) >= (3, 25))
        tools.append({"name": name, "path": path, "version": version, "ready": supported})
    vs = vs_installation()
    return {"tools": tools, "visual_studio": str(vs) if vs else None,
            "desktop_ready": all(t["ready"] for t in tools[:4]) and (os.name != "nt" or vs is not None),
            "winget": shutil.which("winget")}


def installer_command(tool):
    if tool not in PACKAGES:
        raise ValueError("Unknown prerequisite")
    args = ["winget", "install", "--id", PACKAGES[tool], "--exact", "--interactive",
            "--accept-source-agreements", "--accept-package-agreements"]
    if tool == "visual-studio":
        args += ["--override", "--wait --norestart --add Microsoft.VisualStudio.Workload.VCTools "
                 + " ".join("--add " + c for c in VS_COMPONENTS[1:]) + " --includeRecommended"]
    return args


def install(tool):
    if os.name != "nt" or not shutil.which("winget"):
        raise RuntimeError("Windows App Installer/winget is required. Install it from Microsoft, then retry.")
    print("Starting official installer for " + PACKAGES[tool], flush=True)
    code = subprocess.call(installer_command(tool))
    if code:
        raise RuntimeError(f"Installer exited with code {code}. Check its window and retry detection.")
    print("Installation completed. Run the toolchain check again.", flush=True)
