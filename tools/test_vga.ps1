$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
& python (Join-Path $projectRoot 'tools/run_tests.py') @args
if ($LASTEXITCODE -ne 0) { throw 'MGPU regression failed' }
