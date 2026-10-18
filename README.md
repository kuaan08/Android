# Xbox360Recomp

An Xbox 360 adaptation of [SwitchRecompz](https://github.com/kuaan08/Switchrecompz), whose original desktop interface comes from **SwitchRecomp by MZ Labs**. Fork additions are maintained by **katakishi0**, with repository hosting by **kuaan08**.

Xbox360Recomp translates Xbox 360 PowerPC code to C++ ahead of time through ReXGlue, then builds native PC programs or experimental Android ARM64 APKs. A separate runtime supplies kernel services, graphics, audio, input, memory and filesystem behavior.

> **Work in progress.** Importing, compiling, or packaging a title does not establish gameplay compatibility. The Android library APK does not contain a universal interpreter: each playable title needs its own native recompilation. No game data is included.

**Contents:** [Progress](#progress) · [How it works](#how-it-works) · [Architecture](#architecture) · [Desktop app](#desktop-app) · [Build caches](#build-caches) · [Download](#download) · [Getting started](#getting-started) · [Building](#building) · [Documentation](#documentation) · [Acknowledgements](#acknowledgements) · [License](#license)

## Progress

### Implemented features

This table describes code present in the fork, not a list of games confirmed playable.

| Area | Current implementation | Practical limit |
| --- | --- | --- |
| CPU translation | ReXGlue PowerPC/Xenon analysis, C++ generation and native linking | Missing function boundaries, indirect control flow and unsupported guest behavior can prevent execution |
| Input | XEX2 files, extracted folders and XDVDFS ISO/XISO, including XGD1/2/3 partition offsets | Compressed, split, GOD/STFS and automatic title-update merging are not implemented |
| Verification | Structural XEX inspection; bounded ISO table/path checks; SDK version and download digest checks | Structural checks do not prove gameplay compatibility |
| Desktop UI | Original-style top navigation, Recompile/Library/About tabs, left form, status/run cards, console, copy/save logs, recent files, drag/drop and settings dialogs | Nintendo-specific options are replaced with Xbox 360 controls |
| Tool setup | Startup tool detection, missing-tool prompt, official interactive Windows installers and automatic Visual Studio environment loading | The user must approve installation; administrator/installer dialogs remain external |
| Graphics | Desktop SDK Xenos plugin with Direct3D 12 or Vulkan when built into the selected SDK; Android fork Vulkan path | Backend availability and rendering correctness require title/device tests |
| Audio/input | ReXGlue runtime audio and gamepad support; Android SDL lifecycle and controller integration | Android touchscreen gamepad controls are not implemented in this fork |
| Android menu | Dark/green library, system folder/ISO picker, extraction, executable hash matching, per-title launch and automatic start after matching import | The general library APK has no game code; it cannot run an arbitrary ISO |
| APK export | Separate pinned Android ReXGlue runtime and matching host codegen, ARM64 native build, Java/SDL packaging, 16 KB alignment and APK signature verification | Single-XEX projects only; guest DLL title exports stop with an explicit error |
| Per-game settings | Renderer and fullscreen settings stored beside the project | Other title-specific runtime tweaks require source/manifest edits |
| Updates | Explicit GitHub release check, official release link and SHA-256-verified Windows update download | Portable files are replaced after closing the app; Android opens the official release page |
| Build reuse | CMake/Ninja incremental builds, Rust CI caches and Android SDK-source/native-build cache | Reuse depends on matching source, toolchain and configuration |

### Validation and compatibility

Tests use original synthetic input with no commercial data. They cover header bounds, ISO extraction/path rejection, installer command restrictions, update hashes, project state and failure propagation. The XEX fixture contains `li r3,1; blr`, with authored PE/PDATA metadata. It has been translated to C++ and linked into a Windows native executable.

CI also builds the desktop frontend, packages and verifies the Android menu APK, and runs a separate synthetic native Android export job. The results are visible in the [current Actions runs](https://github.com/kuaan08/xbo360/actions). Building an Android binary does not prove physical-device startup, Vulkan rendering, or commercial-game playability.

There is no confirmed commercial-game compatibility or FPS table for this fork.

### Platform status

| Target | Status |
| --- | --- |
| Windows x64 | Native desktop recompiler/workbench and portable distribution |
| Linux x64 | CLI and frontend tests; compatible external Clang toolchain required |
| Windows Direct3D 12 | Through the official SDK Xenos plugin |
| Windows Vulkan | Available only if included in the selected SDK build |
| Android ARM64 menu APK | Library/import menu built from Java with SDK tools |
| Android ARM64 per-title APK | Experimental source-runtime cross-compilation; Android 13+, Vulkan and physical gamepad recommended |
| Android on-device recompilation | Not implemented; game code is generated/compiled on PC |

## How it works

1. Select a game folder, `.xex`, `.iso` or `.xiso`.
2. The importer validates an XDVDFS image and extracts it into a separate assets directory. An extracted directory must contain a unique `default.xex`, or a unique XEX.
3. The selected executable is passed to ReXGlue initialization and code generation. The SDK creates a per-title manifest and C++ application.
4. CMake/Ninja/Clang builds a native host executable. Android export instead uses a separately pinned Android SDK fork and its matching code generator, then cross-compiles with NDK r27c.
5. The native runtime loads the original assets and runs the translated code. Android's menu validates the imported executable's SHA-256 against the compiled title before starting it.

The Android menu can select an ISO and start after successful matching import because its native APK already contains that title's translated code. Importing a different title cannot create new native machine code on the phone.

## Architecture

| Component | Responsibility |
| --- | --- |
| `gui/` | Rust/egui desktop UI, background processes, original-style layout, library, setup/update dialogs and persistent settings |
| `xbo360.py` | Project lifecycle, command orchestration, desktop compilation and launch |
| `iso_import.py` | Bounded XDVDFS table traversal and extraction, XGD partition discovery, path/duplicate checks |
| `prerequisites.py` | Tool/version checks, Visual Studio discovery/environment and fixed official installer commands |
| `updates.py` | Repository-restricted release metadata and digest-verified staged downloads |
| `android_build.py` | Matching Android codegen/runtime build, NDK cross-compilation, APK assembly/signing/verification |
| `android_tools.py` | Explicit Windows Android SDK/NDK/JDK setup with pinned download hashes; adapted from SwitchRecomp |
| `android/` | Original Java menu, SAF import, XDVDFS reader and SDL game Activity |
| ReXGlue desktop SDK | PowerPC translation, runtime and runtime-loaded Xenos GPU plugin |
| Android ReXGlue fork | Android memory/threading/filesystem/bootstrap changes and Vulkan/SDL runtime |

### Runtime subsystems

The SDK implements the guest memory map, function dispatch, kernel/HLE interfaces, thread scheduling primitives, filesystem mapping, audio and controller integration. Xenos handles guest GPU behavior; choosing a backend does not replace title-specific compatibility work.

The desktop SDK is pinned to **0.10.0**, commit `f5337cdc947ff6d4c4196737e2c807a48f2a1fc2`. The Android runtime uses [AlanConstantino/rexglue-skate3-android](https://github.com/AlanConstantino/rexglue-skate3-android) at **`8dd8b369ba2770259776472b981bcecd0dcc11f0`**. Its matching host CLI generates the Android C++ files. These generations are kept separate because their runtime ABIs differ.

The Nintendo ARM64 translator, Horizon services, Maxwell runtime and Nintendo package/key menus are not used for Xbox 360 execution. Their UI positions and workflow are adapted to Xbox input, tool setup, targets and verification.

## Desktop app

The layout follows the original SwitchRecomp frontend: top bar and tool status, Recompile/Library/About navigation, a fixed left form, progress/result card, scrolling console and bottom status bar. Library actions include codegen, build, play, per-game settings, APK export and opening the project folder. Settings include Python/SDK paths, build jobs, renderer and Android paths.

On startup the app checks requirements in the background. Missing requirements open **Install required build tools?**. Nothing is installed until the user chooses a component and confirms. Windows installers use fixed winget package IDs; Visual Studio setup includes C++ tools, Clang and CMake integration. Android tools use verified vendor archives after confirmation of the Android SDK/NDK license.

The app discovers the Visual Studio installation with `vswhere`, captures `vcvars64.bat` and adds compiler/CMake locations to the child build environment. Starting from a developer command prompt is no longer required when detection succeeds. The original full compiler log remains in the project folder; the UI bounds its retained lines.

## Build caches

Generated projects preserve their CMake/Ninja build directories. Android exports preserve their separate generated C++ and native build directory. The pinned Android source/runtime host build resides in the app's cache. CI caches Rust dependencies and the Android source/build tree. Clearing a cache does not fix unsupported guest code.

## Download

- [Releases and update packages](https://github.com/kuaan08/xbo360/releases/latest)
- [Actions artifacts and validation logs](https://github.com/kuaan08/xbo360/actions/workflows/ci.yml)

The Windows ZIP contains the frontend, Python, the desktop ReXGlue SDK, Android exporter sources and documentation. The Android library APK contains the import/menu implementation. Neither package includes a commercial title. Native APKs exported locally are specific to the chosen executable/version.

The Updates button checks this repository's releases. Windows update downloads require the release asset's published SHA-256 and size. Extract the verified ZIP and replace the portable application after closing it; user settings live outside the application directory. Android's Updates button opens the same official release page for user-controlled installation.

## Fixing unresolved analysis branches

For the exact tested *Rise of the Tomb Raider* XEX revision, a [detailed disassembly and PDATA analysis](docs/RISE_TOMB_RAIDER_ANALYSIS.md) establishes a missing 112-byte function at `0x82C21240`. **Library → Function hints → Check verified hints for this XEX** checks the original executable's SHA-256 and offers a verified suggestion only for that revision. You must explicitly select and save the hint. Other revisions receive no guessed sizes. CLI: `python xbo360.py suggest-hints "D:\\Ports\\my_game"`. Successful C++ generation and gameplay remain unconfirmed.


Some games reach the ReXGlue `Validate` phase and stop with an unresolved branch target, e.g. the reported `0x82C21240 from 0x82C22B14: b 0x82C21240`. In PowerPC a `b` can be a jump into an existing function or a tail call. **The log does not establish a valid function size.**

The **Library → Function hints** window shows unresolved branches from the project's `build.log`. You can select the target address, disassemble the corresponding game executable externally, enter the verified function size (in bytes, divisible by four) and optionally a parent address for an out-of-line function chunk. The application creates `xbo360-function-hints.toml`, adds the file to `[entrypoint].includes`, and leaves the original game intact. Existing projects can be regenerated without initializing over their directories.

Equivalent CLI commands:

```powershell
python xbo360.py diagnose "D:\Ports\my_game"
python xbo360.py function-hint "D:\Ports\my_game" --address 0x82C21240 --size VERIFIED_BYTE_COUNT
python xbo360.py codegen "D:\Ports\my_game"
```

`VERIFIED_BYTE_COUNT` is a placeholder; **64, 128 or any other size would be a guess without analyzing the XEX**. The tool refuses unaligned addresses and sizes, conflicting edits and unsafe manifest paths.

The optional Force checkbox appears on the Recompile page and in Settings (default off). On the CLI, use `python xbo360.py codegen "D:\Ports\my_game" --force`, or add `--force` to `build`/`recompile`. It passes the global ReXGlue `--force` before `codegen`; this allows further diagnosis despite analysis validation problems, but **it cannot fix control flow, guarantee native C++ compilation, or make an incompatible game playable**.

## Getting started

### Windows

1. Extract the complete Windows ZIP and start `Xbox360Recomp.exe`.
2. In the prerequisite prompt, install the missing Visual Studio C++/Clang, CMake and Ninja components. Complete their installer dialogs, then choose **Check again**.
3. Select an XEX, game folder or ISO, choose a separate empty project directory and use a lowercase project name.
4. Verify input, prepare the project or run **Recompile + build**. Use Library for subsequent builds and launch.
5. For Android, install the Android tools from Settings, prepare the project, then choose **Library → Export APK**.

### Android

The general menu APK can import a folder or seekable ISO/XISO through Android's file picker and show its library. Playing requires installing the per-title native APK produced by the desktop exporter. In that APK, import matching files or ISO; successful SHA-256 validation starts the native title automatically. Unsupported executable versions produce an explicit message.

ISO providers must support random access. Download cloud-hosted images locally first. Extraction uses app-specific external storage and may require many GiB of free space. Keep the app open during import. A physical gamepad is currently required for usable gameplay input.

## Building

Python 3.11+ is required for source use. Desktop native builds require Clang 20+, CMake 3.25+, Ninja, and the Windows C++/Windows SDK toolchain where applicable.

```powershell
python xbo360.py install-sdk
python xbo360.py toolchain
python xbo360.py inspect "D:\MyGame.iso"
python xbo360.py recompile "D:\MyGame.iso" --project "D:\Ports\my_game" --name my_game
python xbo360.py run "D:\Ports\my_game"
```

Input verification does not extract ISO files. Recompile/prepare extraction refuses to overwrite an existing assets directory. Resume an existing project with `codegen`/`build` rather than initializing over it.

```powershell
python xbo360.py setup-android --yes
python xbo360.py android
python xbo360.py android --project "D:\Ports\my_game" --runtime --jobs 4
python xbo360.py update --download
```

`setup-android --yes` records explicit user consent to tool setup. Android export requires JDK 17, SDK platform/build-tools 35, NDK **27.2.12479018**, Git and a source-build-capable desktop Clang environment. Set `--android-sdk`, `--ndk` and `--sdk-source` to select existing tools. Linux additionally needs the SDK's GTK/Vulkan development dependencies. The first native Android export downloads the pinned runtime and its submodules and builds the matching host code generator; this can be lengthy.

The exporter creates aligned, signed development APKs and verifies their signatures. The local development keystore is retained in the app cache; keep that key for compatible updates. CI artifacts are development builds, not a production signing setup. Android guest DLL modules currently require title-specific integration and are rejected by the generic exporter.

```bash
python3 -m unittest discover -s tests -v
cargo test --locked --manifest-path gui/Cargo.toml
cargo build --release --locked --manifest-path gui/Cargo.toml
```

## Documentation

- [Architecture and upstream decisions](docs/ARCHITECTURE.md)
- [Android export and validation](docs/ANDROID.md)
- [Review notes](docs/REVIEW.md)
- [Changes](CHANGELOG.md)
- [Third-party notices](THIRD_PARTY.md)

## Acknowledgements

**SwitchRecomp by MZ Labs** is the original desktop frontend foundation, via `kuaan08/Switchrecompz`. Its styling, icon foundation, background job machinery and Android-tool installer are reused/adapted with attribution. Fork additions: **katakishi0**; hosting: **kuaan08**.

**ReXGlue by Tom Clay and contributors**, **Xenia**, **XenonRecomp by hedge-dev** and **rexdex's recompiler** provide the underlying research and runtime foundations. The Android path additionally credits **AlanConstantino, Andrew Nakas, Buku313 and contributors**. The XDVDFS reader was independently implemented with the format/partition-offset behavior checked against [antangelo/xdvdfs](https://github.com/antangelo/xdvdfs).

## License

The workbench is Apache-2.0; preserve [LICENSE.txt](LICENSE.txt) and [NOTICE.txt](NOTICE.txt), including **SwitchRecomp by MZ Labs**. ReXGlue, its Android fork, SDL and all other dependencies retain their own licenses. See [THIRD_PARTY.md](THIRD_PARTY.md).
