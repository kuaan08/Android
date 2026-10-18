#!/usr/bin/env python3
"""Verify Flutter FFI symbol names against an actually packaged ARM64 engine.

Run after building the APK, not only against native C++ source code: Android
Gradle packaging and the dynamic linker are part of the runtime contract.
"""
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

root = Path(__file__).resolve().parents[1]
dart = (root / "lib/core/native/engine_bridge.dart").read_text(encoding="utf-8")
symbols = set(re.findall(r"lookupFunction<[^;]*?>\s*\(\s*'([^']+)'", dart))
if len(symbols) < 20:
    raise SystemExit(f"Expected 20+ FFI bindings, found {len(symbols)}: {sorted(symbols)}")

apk = Path(sys.argv[1] if len(sys.argv) > 1 else
           "build/app/outputs/flutter-apk/app-debug.apk")
with zipfile.ZipFile(apk) as archive:
    name = "lib/arm64-v8a/libxbox360recomp.so"
    if name not in archive.namelist():
        raise SystemExit("ERROR: Android APK has no arm64-v8a/libxbox360recomp.so")
    with TemporaryDirectory() as temp:
        binary = Path(temp) / "libxbox360recomp.so"
        binary.write_bytes(archive.read(name))
        result = subprocess.run(["readelf", "-W", "--dyn-syms", str(binary)],
                                check=True, capture_output=True, text=True)
        exported = set(re.findall(r"\b(x360_[A-Za-z0-9_]+)(?:@@\S+)?\s*$",
                                  result.stdout, re.MULTILINE))
missing = sorted(symbols - exported)
print("FFI Dart lookups:", len(symbols))
print("Native ARM64 exported x360_* symbols:", len(exported))
if missing:
    print("ERROR: Dart looks up missing native symbols: " + ", ".join(missing))
    raise SystemExit(1)

# ABI regression: these functions are float-returning in native/src/bridge/metrics.cpp.
for symbol in ("x360_metrics_fps", "x360_metrics_frame_time", "x360_metrics_gpu_temp"):
    pattern = r"lookupFunction<Float Function\(\), double Function\(\)>\('" + symbol + r"'\)"
    if not re.search(pattern, dart):
        raise SystemExit(f"ERROR: {symbol} must use Float, not Double (ARM64 ABI)")

if "_engineInit(1);" not in dart or "if (result != 0)" not in dart:
    raise SystemExit("ERROR: native initialization result is not checked")
print("PASS: packaged ARM64 engine satisfies Flutter native FFI contract")
