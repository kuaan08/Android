# Architecture and research notes

## 0.2.0 additions

The desktop frontend now follows the original Recompile/Library/About layout and adds explicit prerequisite setup, release checks/downloads, folder/ISO input and Android export controls. See README.md for the component map and docs/REVIEW.md for findings addressed.

Android uses a separate source SDK generation: AlanConstantino/rexglue-skate3-android at `8dd8b369ba2770259776472b981bcecd0dcc11f0`. Its own host CLI generates code for its own runtime. This separation avoids the incompatible image-info/codegen/runtime APIs between that fork and desktop SDK 0.10.0. Native generation and packaging live in `android_build.py`; the Java menu imports assets, checks the exported executable hash and starts the matching SDL Activity. No universal on-device interpreter is present.

## Reviewed sources

| Source | Revision | Decision |
| --- | --- | --- |
| [kuaan08/Switchrecompz](https://github.com/kuaan08/Switchrecompz) | `c33f097` | Reuse Rust/egui frontend foundations and process/log handling; retain attribution |
| [rexglue/rexglue-sdk](https://github.com/rexglue/rexglue-sdk) | stable 0.10.0, `f5337cdc947ff6d4c4196737e2c807a48f2a1fc2` | Use official binary SDK as translator, runtime, and project generator |
| [ReXGlue CLI implementation](https://github.com/rexglue/rexglue-sdk/blob/v0.10.0/src/rexglue/commands/init_command.cpp) | same SDK tag | Use manifest-first, hyphenated command options verified with the official executable |
| [ReXGlue project templates](https://github.com/rexglue/rexglue-sdk/tree/v0.10.0/resources/templates/init) | same SDK tag | Preserve SDK-generated integration and platform presets |
| [hedge-dev/XenonRecomp](https://github.com/hedge-dev/XenonRecomp) | architectural alternative | Not a second backend in this fork; ReXGlue integrates its own codegen and runtime |
| [Xenia](https://github.com/xenia-project/xenia) | foundational research credited by ReXGlue | Runtime compatibility comes through ReXGlue rather than transplanting Switch services |

The public ReXGlue wiki still contains examples using `--app_name`, `--app_root`, and `*_config.toml`. The pinned release binary instead accepts `--project-name`, `--project-root`, `--xex-path`, and `*_manifest.toml`. The wrapper follows the binary and tagged source. Updating the dependency requires reviewing command and template contracts again.

## Boundaries

`gui/` owns the host UI and streams the Python child's output. The child has its own process group on Unix; cancellation kills the group. On Windows, cancellation uses `taskkill /T /F`. Closing the UI cancels an active job. A cancelled run can leave intermediate files; use an existing project's codegen/build actions to resume after inspecting its log.

`xbo360.py` owns validation, project state, SDK install/verification, and command orchestration. Commands use argv arrays and never interpolate paths into a shell. State is written through a temporary file and replaced. Project status records preparation, generation, build and failure; it is not a compatibility rating.

ReXGlue owns binary loading, function discovery, instruction translation and guest runtime. The wrapper does not pretend the Switch A64 translator can decode PowerPC instructions. Xenos and Maxwell shader languages/command processors also require different implementations.

## SDK adaptations

The SDK initializer lowercases filesystem paths. After generation the wrapper rewrites only host paths in the manifest, matching discovered guest DLLs against the original filesystem entries. Conflicting DLL names differing only in case produce an explicit error. Guest path conventions and generated source directory names remain managed by the SDK.

The CMake application target is changed to request the Xenos GPU plugin. The application header gains an explicit selected-XEX hook and a renderer variable that calls the SDK's GPU plugin API. Missing or incompatible plugins remain errors. Auto-generated files under `generated/` are not hand-reimplemented.

The exact official SDK download SHA-256 values are in `xbo360.py`. Existing user-selected SDKs are checked by their version output; the version check is an API compatibility check, not proof that a user-selected installation is byte-identical to the official release.

## Verification scope

Automated tests cover header validation, path escaping/casing, refusal of invalid project paths, SDK mismatch, child failure propagation, and stale executable invalidation. The optional integration tests execute the official SDK initializer, translate an original XEX with PE/PDATA metadata and the instructions `li r3,1; blr`, and verify that incomplete synthetic input fails cleanly. Windows CI also compiles the generated fixture project and its runtime integration. Rust tests exercise the reused log/progress parser.

No commercial executable was supplied for this adaptation, and no successful commercial translation or gameplay test is claimed. SDK codegen, linking, runtime startup and game behavior must be evaluated separately for a selected title. An ELF probe also encountered the SDK's requirement for PE exception metadata; ELF is not exposed as a supported workbench input.

## Follow-up work

Validate a user-selected title end to end; add richer per-title configuration editing and compatibility reports. Version 0.2.0 adds ISO import, guided compiler setup and the separate Android path described above. STFS import and Android guest DLL packaging still require separate implementations and tests.
