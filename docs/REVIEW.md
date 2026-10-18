# Review of 0.2.0

## Findings addressed

- The first Xbox fork reduced the original frontend to a stacked form. The Recompile/Library/About chrome, fixed left form, result card, console, status bar, recent input and drag/drop behavior now follow the original layout. Platform-specific Nintendo controls are replaced by Xbox 360 controls.
- Users previously needed to find toolchain prerequisites and start from a developer shell. The app now probes tools, asks before installation, starts fixed official installer packages, captures Visual Studio's build environment, and resolves executables from that child environment.
- An XEX-only pipeline could not use disc images. The new XDVDFS reader detects XISO/XGD partitions, checks directory bounds/cycles/duplicates and rejects traversal before PC extraction writes files. Original images are opened read-only.
- Desktop and Android SDK runtime ABIs differ. Android uses a separately pinned fork and its matching code generator rather than reusing incompatible 0.10.0 generated files.
- Importing an arbitrary ISO into an APK cannot produce native code for it. Per-title metadata contains the exported executable's hash; Android validates it before enabling/starting native execution.
- The previous package script copied only the original Python entrypoint. It now includes all helper modules and Android sources, and smoke-checks packaged tool discovery.
- The Android fork's standalone Linux host build omitted the SIMD baseline required by `memory.cpp`. A deferred CMake target option supplies x86-64-v2 for `rexcore` without altering the pinned source tree or changing the ARM64 build target.
- Native APKs retain license files from the Android runtime and its vendored dependencies, along with the exact source revision.
- Failed codegen/build continues to clear stale executable state. Update downloads enforce the repository, exact asset name, size and SHA-256 and remove failed partial downloads.

## Verification

Python tests cover real SDK codegen on an original fixture, XEX/ISO rejection and extraction, update integrity, installer command restrictions and stale-state behavior. Rust tests cover log/progress handling. CI additionally compiles a Windows native fixture, packages Windows and Android outputs and attempts the full Android fixture export against the pinned runtime source.

Installer dialogs are not executed in CI; command construction and build-environment detection are checked separately. No commercial-game or physical-device test is claimed. Android source/runtime builds, package assembly and actual device gameplay are different validation stages.

## Remaining constraints

Single-XEX Android export, physical-gamepad input, no on-device recompilation, no compressed/split/GOD images, no automatic title update integration, and no commercial-game compatibility table. The Windows update package is downloaded and verified; replacing an open executable is left to the user after closing the app.
