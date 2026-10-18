# Third-party attribution

- SwitchRecomp by MZ Labs, Apache-2.0: `gui/src/theme.rs`, `icon.rs`, and `job.rs` are derived from the SwitchRecompz frontend. Original notices and the full license are preserved in NOTICE.txt and LICENSE.txt. Modified files identify the Xbox 360 adaptation.
- ReXGlue SDK by Tom Clay and contributors, BSD-3-Clause: downloaded as an independent, version-pinned SDK; original license is in `ci/licenses/ReXGlue-BSD-3-Clause.txt`. Its Xenia-derived components and other dependencies retain their upstream licenses. Official SDK packages include their own third-party license files; the packaging workflow preserves them.
- Rust dependencies, including egui/eframe, serde, serde_json and rfd, retain their package licenses. Cargo.lock records exact resolved versions.
- `android_tools.py` is adapted from SwitchRecomp by MZ Labs under Apache-2.0; it retains the verified vendor-archive installation design.
- Android native exports use AlanConstantino/rexglue-skate3-android at `8dd8b369ba2770259776472b981bcecd0dcc11f0`, with Android integration by AlanConstantino, Andrew Nakas, Buku313 and contributors. SDL Java source is taken from that runtime's pinned SDL submodule during export. Those sources retain their original notices and licenses.
- The original Python/Java XDVDFS readers were written for this fork; the format and XGD offsets were checked against antangelo/xdvdfs (MIT). No source from that repository is vendored.
- Windows portable packages include unmodified CPython; its license and other text files remain in the embedded distribution.

No game executables, game assets, firmware, or keys are included.
