# ViaXTrace Xbox360RecompAndroid fork

- Original source: https://github.com/ViaXTrace/Xbox360RecompAndroid
- Upstream revision: cd37586c67c781bdfbbd164c034892a9b9836a6e
- The previous static ReXGlue project remains recoverable from the branch backup/rexglue-before-viaxtrace.
- This main branch now contains only the ViaXTrace Flutter / C++ ARM64 JIT project.

## Repairs

- Android SAF ISO/XISO import streams file data in 1 MiB chunks; no whole-ISO RAM buffering.
- Import verifies XDVDFS/ISO9660 header, computes a checksum and reports errors.
- JIT memory initialization is deferred until Play rather than app startup or ISO import.
- Native ISO parser handles XGD partition offsets, 64-bit sector offsets, and bounded directory traversal.
- Host CI synthetic ISO smoke tests; no actual game data is included.

## Important limitations

Successful ISO import does not imply the experimental JIT/HLE/Vulkan engine will execute the game.
The upstream README advertises GPL-2.0, but no standalone LICENSE file is present in the upstream source tree; please clarify the license with the upstream maintainer before redistribution. Original author attribution is preserved.

## Black screen and Turnip status (GPU diagnostics)

The experimental JIT successfully starting a thread **does not mean that game
graphics render**. In the first retail-title test (Ben 10 Ultimate Alien
Cosmic Destruction), the overlay showed **0 FPS, 1 JIT block, black screen**.
These readings are not evidence of playable title compatibility.

The native GPU now exports **real** diagnostic counters: renderer
initialization status, Vulkan frames presented, Xenos PM4 packets, PM4 draw
packet requests, shader compilation attempts, successfully created Vulkan
shader modules and failures. On the in-game screen (after several seconds),
the black-screen diagnostic panel describes the actual blocked stage and
offers **Copy diagnostic**, with no game files included. Shader status is
displayed only when actual shader requests exist; no synthetic progress bar.

**Known limitations, not completed fixes:**

- The JIT/HLE lacks a complete Xenos PM4 submission path.
- Xenos shader microcode → SPIR-V is currently a placeholder, not a game
  shader translator. Even a presentable Vulkan clear frame is not gameplay.
- Native PM4 DRAW_INDX handling does not yet submit actual Vulkan draw calls.
- The renderer currently links Android's system `libvulkan.so`. Existing
  `driver_loader.cpp` uses `dlopen` only; it **does not redirect** Vulkan
  dispatch tables to a custom Turnip driver. The old Turnip settings toggle
  never changed the actual driver. Until libadrenotools with real Vulkan
  function routing is integrated/tested, Turnip is explicitly marked
  unavailable and the system driver remains active.
- Some game settings were UI-only placeholders. The settings screen now
  calls that out and saves **only implemented options** (per-game JIT
  thread count used on the next launch and GPU diagnostic visibility).
- For 6 GB RAM devices, 1–2 JIT threads are the conservative starting point.
  Raising JIT thread count does not guarantee an FPS improvement.

To investigate a black screen, report the copied GPU diagnostic counters.
If PM4 packets and shader requests are zero, the bottleneck is before GPU
compilation; installing Turnip alone cannot solve it.
