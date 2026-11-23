[CmdletBinding(SupportsShouldProcess)]
param([switch]$KeepTests, [switch]$KeepBuild)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$directories = @('.Xil', 'MGPU.cache', 'MGPU.hw', 'MGPU.sim', 'MGPU.runs',
    'MGPU.ip_user_files', 'MGPU.gen', 'MGPU.srcs/utils_1', 'xsim.dir')
$files = @('clockInfo.txt', 'dfx_runtime.txt', 'vivado.jou', 'vivado.log')
$targets = @($directories + $files | ForEach-Object { Join-Path $projectRoot $_ })
$output = Join-Path $projectRoot 'out'
if (($KeepTests -or $KeepBuild) -and (Test-Path -LiteralPath $output)) {
    $targets += Get-ChildItem -LiteralPath $output -Force | Where-Object {
        -not (($KeepTests -and $_.Name -eq 'tests') -or ($KeepBuild -and $_.Name -eq 'vga_current'))
    } | Select-Object -ExpandProperty FullName
    if ($KeepBuild) { $targets += Join-Path $output 'vga_current/.Xil' }
} else {
    $targets += $output
}
$targets += Get-ChildItem -LiteralPath (Join-Path $projectRoot 'tools') -Directory -Filter '__pycache__' | Select-Object -ExpandProperty FullName
foreach ($target in $targets) {
    $resolved = [IO.Path]::GetFullPath($target)
    if (-not $resolved.StartsWith($projectRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Cleanup target is outside the project: $resolved"
    }
    if ((Test-Path -LiteralPath $resolved) -and $PSCmdlet.ShouldProcess($resolved, 'Remove generated output')) {
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
