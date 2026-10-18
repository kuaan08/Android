# Changelog

## 0.3.1

- Inspect a supplied Rise of the Tomb Raider XEX and confirm a missing PowerPC leaf function at `0x82C21240` with a 112-byte extent, based on disassembly and adjacent PDATA entries.
- Show checksum-matched known hints in **Library → Function hints**, requiring explicit user selection and save; other revisions receive no suggested size.
- Add the read-only `suggest-hints` CLI and test that it never mutates the XEX or project and refuses nonmatching checksums.
- Document the evidence and test procedure; gameplay compatibility remains unconfirmed.


## 0.3.0

- Add a persistent, opt-in Force checkbox in the Recompile page and Settings. It reaches the desktop codegen process via the real ReXGlue global `--force` flag; ordinary builds still validate normally.
- Identify `UnresolvedCall` branches in existing project logs, including original source and target addresses. A branch alone does not prove a function boundary.
- Add **Library → Function hints** for reviewed function addresses and explicit sizes in bytes, plus an optional parent for a discontiguous code chunk.
- Write manual hints to `xbo360-function-hints.toml` and include it in the project manifest, without rewriting original XEX or assets.
- Add `diagnose` and `function-hint` CLI commands, regression tests and safety warnings. No commercial-game compatibility is implied.


## 0.2.0

- Restore the original-style Recompile/Library/About interface, fixed form, result card, console, status bar, recent inputs and drag/drop.
- Detect missing prerequisites at startup and ask before starting official Visual Studio/Clang/CMake/Ninja/Git/Java installers; automatically load the Visual Studio environment for builds.
- Add XDVDFS XISO/XGD1/2/3 inspection/extraction and folder input.
- Add explicit verified Android SDK/NDK/JDK setup, Android library/menu APK and experimental per-title ARM64 export using a separately pinned Android runtime and matching codegen.
- Validate imported Android executables against the compiled title and start matching imports automatically.
- Add per-game launch settings and official release checks with digest-verified Windows downloads.
- Expand tests, packaging checks, native Android fixture validation and technical documentation.

## 0.1.0

- Adapt SwitchRecomp frontend foundations to an Xbox 360 PC recompilation workbench.
- Add XEX2 header inspection, ReXGlue 0.10.0 installation with pinned hashes, project initialization, codegen, CMake build and launch commands.
- Preserve host path casing, select the requested XEX at runtime, and stage/configure the Xenos plugin.
- Add persistent project list, streaming logs, cancellation and toolchain checks.
- Add tests and Windows portable artifact workflow. Commercial-game compatibility remains unvalidated.
