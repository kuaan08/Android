# Android

There are three Android paths. The general library APK provides a dark/green menu, SAF folder/ISO selection, XDVDFS extraction and imported-game metadata; it contains no native game code. A per-title APK also includes `libxbo_game.so`, the matching Android `librexruntime.so`, `libc++_shared.so` and SDL Java integration. An optional experimental launcher can additionally generate C++ on-device for a single-XEX project, but does not compile that output into a game APK.

Native export uses `AlanConstantino/rexglue-skate3-android` pinned to `8dd8b369ba2770259776472b981bcecd0dcc11f0`. That fork contains Android memory mapping, shared-memory, threading, filesystem, SDL bootstrap and lifecycle changes. Its host CLI generates code specifically for its runtime ABI. Desktop SDK 0.10.0 output is kept separate and is never presented as ABI-compatible with this older Android runtime.

## Build

Install JDK 17, Android platform/build-tools 35 and NDK r27c (27.2.12479018), plus the host SDK's compiler dependencies. The Windows app offers explicit tool installation. Linux users can use sdkmanager and their system package manager.

```bash
python xbo360.py android
python xbo360.py android --project /path/to/prepared-project --runtime --jobs 4
python android/build_ondevice_codegen.py --sdk /path/to/Android/Sdk --ndk /path/to/Android/Sdk/ndk/27.2.12479018 --jobs 4
```

The first command builds only the menu APK. The second initializes a separate Android codegen project, compiles the matching host codegen if absent, generates the title code, builds an ARM64 shared library and packages/verifies a signed development APK. The third builds the optional launcher with a JNI codegen bridge and adds a per-game “Generate C++ on this device” action. Original game assets are never embedded in the exported APK.

The on-device bridge reuses ReXGlue's `InitProject` and project recompiler. It currently accepts one XEX, rejects guest DLLs, and writes generated sources into app-private storage. The launcher exports those sources plus a portable manifest and relative XEX metadata through the system file picker; original game data is not included. An experimental Termux builder and NDK-sysroot helper now exist, but neither the complete ReXGlue/game build nor APK packaging has been validated on a real Termux device. See [`android/ondevice/README.md`](../android/ondevice/README.md) and [`termux/README.md`](../termux/README.md) for the current implementation and limitations.

Native projects currently accept a single XEX. Discovered guest DLL modules are rejected rather than packaged incorrectly. The original assets remain separate and are selected/imported on the phone. The app checks the executable's SHA-256 against the value captured at export; a different game/version cannot be launched using the compiled code.

## On the phone

Android 13+ and ARM64 are the current minimum. Vulkan and a physical gamepad are required for the intended native game path. The selected upstream runtime can impose further CPU/GPU requirements; no device compatibility is established by packaging tests alone.

Choose an ISO/XISO or an extracted folder using the system picker. ISO providers must support seeking, so local storage/USB-backed documents are preferable to cloud streams. Imported data is staged under app-specific external storage. Failed imports remove the incomplete stage; completed imports receive a library marker. A matching per-title APK starts automatically after validation. The general menu instead explains the need for a native export.

The native Activity runs in a separate process. Leaving that Activity ends its process so another session does not reuse stale SDL/runtime state. The menu remains in the application process. The experimental JNI can generate PowerPC recompilation sources and export them. The Termux builder is a separate experimental path; a successful minimal ARM64 Android shared-library probe is not proof that the full title builds or runs, and source generation alone does not make the title playable.

## Device diagnostics and test builds

The launcher includes **Device diagnostics (copy)**. It reports Android API/ABIs, whether Android advertises Vulkan, packaged native libraries, free library storage, memory availability and whether optional JNI codegen initialized. It copies the report to the clipboard; the report excludes game contents, filenames, account identifiers and keys. Vulkan feature presence does not prove a game can render correctly.

The CI runs the real Android Java XDVDFS reader on authored synthetic XISO and XGD3 images and verifies that path traversal, corrupted volume headers and truncated entries are rejected. The Android build job generates three distinct artifacts:

- `Xbox360Recomp-Android`: plain library APK, without native game or codegen binaries.
- `Android-native-validation`: compiled, signed synthetic-title APK plus build/package logs; not a playable commercial game.
- `Xbox360Recomp-Android-Codegen`: experimental library APK with ReXGlue JNI source generation, but no on-device C++ compilation or playable game.

For device failures, reproduce the issue with the APK installed, copy the diagnostics in the app and collect relevant ADB logs:

```sh
adb logcat -c
# Reproduce the problem on the phone, then:
adb logcat -d -b main,system,crash -v threadtime > xbo360-android-log.txt
```

Review logs for private data before sharing. The `crash` buffer may expose native faults not captured by the launcher UI. No test artifact should be interpreted as proof of game compatibility.

## Tests and remaining validation

CI assembles the Java menu with javac/D8/aapt2, aligns it for 16 KB pages, signs it and runs APK signature verification. The native job uses an original two-instruction XEX fixture and compiles its matching Android runtime/library. Consult the actual Actions result for the current revision.

No physical Android device is available in this environment. App startup, storage-provider behavior, controller input, Vulkan rendering, thermal behavior and commercial-game compatibility still require device tests. The menu and native fixture are distinct artifacts; neither is a compatibility claim for arbitrary games.

Local exports reuse a development keystore in the application cache. Preserve it for in-place updates. Release signing with a private production key is separate. The Android Updates button opens [this mobile repository's releases](https://github.com/kuaan08/Android/releases/latest); Android remains responsible for user approval of package installation.
