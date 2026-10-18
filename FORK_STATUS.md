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