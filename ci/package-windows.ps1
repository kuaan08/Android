$ErrorActionPreference = 'Stop'
$stage = Join-Path $PWD 'dist/Xbox360Recomp'
New-Item -ItemType Directory -Force -Path $stage | Out-Null
Copy-Item gui/target/release/Xbox360Recomp.exe $stage
Copy-Item *.py,README.md,LICENSE.txt,NOTICE.txt,THIRD_PARTY.md $stage
Copy-Item android (Join-Path $stage 'android') -Recurse
Copy-Item docs (Join-Path $stage 'docs') -Recurse
Copy-Item sdk (Join-Path $stage 'sdk') -Recurse
Copy-Item ci/licenses (Join-Path $stage 'licenses') -Recurse
$pythonZip = Join-Path $PWD 'dist/python-embed.zip'
# Official Python embedded distribution. Keep its license and DLLs intact.
Invoke-WebRequest 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip' -OutFile $pythonZip
Expand-Archive $pythonZip (Join-Path $stage 'python') -Force
& (Join-Path $stage 'python/python.exe') (Join-Path $stage 'xbo360.py') --version
if ($LASTEXITCODE -ne 0) { throw 'Embedded Python smoke test failed' }
& (Join-Path $stage 'python/python.exe') (Join-Path $stage 'xbo360.py') toolchain
if ($LASTEXITCODE -ne 0) { throw 'Packaged setup detection failed' }
& (Join-Path $stage 'sdk/bin/rexglue.exe') --version
if ($LASTEXITCODE -ne 0) { throw 'Packaged SDK smoke test failed' }
Compress-Archive -Path $stage -DestinationPath dist/Xbox360Recomp-Windows-x64.zip -Force
