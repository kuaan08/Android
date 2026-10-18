# Analysis finding: Rise of the Tomb Raider (Xbox 360)

This note contains **no game executable, assets, proprietary source code or keys**. It documents the metadata and the single control-flow issue observed while reviewing one user-provided XEX. It does not claim commercial-game compatibility.

## Exact XEX fingerprint

- Title ID: `53510823`
- Media ID: `2427ED57`
- Version: `0.0.0.6`
- XEX2 file size: 16,531,456 bytes
- SHA-256: `9f718cac4cc7fb33ec7204e90d0901387f81e18c953eb1f90c40be5e2e3ff021`
- XEX is encrypted with BASIC compression. The analyst reconstructed the executable image and examined PDATA and PowerPC instructions without redistributing it.

## Finding and rationale

The codegen log reported `UnresolvedCall 0x82C21240 from 0x82C22B14`. Direct PPC branch `b` from `0x82C22B14` targets `0x82C21240`, following an `addi` at `0x82C22B10`; the source lies outside the prior PDATA function. The target is an apparent leaf-function entry not present in PDATA:

- Previous registered PDATA function: `0x82C21110` through `0x82C21240` (exclusive).
- Unregistered function starts: `0x82C21240`.
- Last instruction `0x82C212AC`: `blr`.
- Next registered PDATA function starts: `0x82C212B0`.
- Evidenced extent: `0x82C21240..0x82C212B0`, **0x70 = 112 bytes**.

This boundary is independently supported by return/control-flow and PDATA adjacency. It is not an arbitrary guess; nevertheless, ReXGlue codegen and gameplay have **not been retested successfully** after adding the hint.

## Apply to an existing prepared project

In desktop **Library → Function hints → Check verified hints for this XEX**, only the exact SHA-256 match exposes the evidence-backed 112-byte suggestion. Choose **Use verified hint**, explicitly save the boundary, then retry **Generate C++** with **Force disabled**. The verification occurs on the PC and no game data is uploaded.

Equivalent CLI:

```powershell
python xbo360.py suggest-hints "D:\Ports\my_game"
python xbo360.py function-hint "D:\Ports\my_game" --address 0x82C21240 --size 112
python xbo360.py codegen "D:\Ports\my_game"
```

This writes `xbo360-function-hints.toml` and includes it from `[entrypoint].includes`. Do not delete or reinitialize the existing project. Alternatively, with ReXGlue 0.10.0, insert the TOML below at the end of the manifest:

```toml
[entrypoint.functions]
"0x82C21240" = { size = 112 }
```

Do not use both mechanisms for the same function address at the same time. If subsequent errors appear, preserve the updated build log; missing function boundaries can occur more than once. Force is diagnostic and does not fix codegen or runtime behavior.
