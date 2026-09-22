$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$outputDir = Join-Path $projectRoot 'out/vga_current/tests'
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
$rtl = Get-ChildItem (Join-Path $projectRoot 'MGPU.srcs/sources_1/new/*.v') | ForEach-Object FullName
$sequenceBinary = Join-Path $outputDir 'space_sequence_tb.vvp'
& iverilog -g2012 -DSPACE_SCENE_STUB -s space_sequence_tb -o $sequenceBinary (Join-Path $projectRoot 'MGPU.srcs/sources_1/new/top.v') (Join-Path $projectRoot 'MGPU.srcs/sim_1/new/space_sequence_tb.v')
if ($LASTEXITCODE -ne 0) { throw 'Sequence test compilation failed' }
& vvp $sequenceBinary
if ($LASTEXITCODE -ne 0) { throw 'Sequence/geometry test failed' }
foreach ($testName in @('vga_tb', 'logo_vga_tb', 'space_vga_tb')) {
    $testbench = Join-Path $projectRoot "MGPU.srcs/sim_1/new/$testName.v"
    $binary = Join-Path $outputDir "$testName.vvp"
    & iverilog -g2012 -s $testName -o $binary @rtl $testbench
    if ($LASTEXITCODE -ne 0) { throw "Compilation failed: $testName" }
    Push-Location $projectRoot
    try {
        & vvp $binary
        if ($LASTEXITCODE -ne 0) { throw "Simulation failed: $testName" }
    } finally { Pop-Location }
}

# Preserve the user's existing rendered image/log: run the original testbench
# in its own working directory, with an explicit top and the new vga.v included.
$regressionDir = Join-Path $outputDir 'gpu_regression'
New-Item -ItemType Directory -Force -Path (Join-Path $regressionDir 'out') | Out-Null
$binary = Join-Path $regressionDir 'mgpu_tb.vvp'
& iverilog -g2012 -s mgpu_tb -o $binary @rtl (Join-Path $projectRoot 'MGPU.srcs/sim_1/new/mgpu_tb.v')
if ($LASTEXITCODE -ne 0) { throw 'Original GPU testbench compilation failed' }
Push-Location $regressionDir
try {
    & vvp $binary +DEMO
    if ($LASTEXITCODE -ne 0) { throw 'Original GPU regression failed' }
} finally {
    Pop-Location
}
