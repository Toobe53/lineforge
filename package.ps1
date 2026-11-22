# LineForge — package the add-on as an installable Blender zip.
# GPL-2.0-or-later.
[CmdletBinding()]
param(
    [string]$Version = '0.2.0'
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$addon = Join-Path $root 'addon\lineforge'
$dist = Join-Path $root 'dist'
$pyd = Join-Path $addon 'bin\win64\lineforge_core.pyd'

if (-not (Test-Path $pyd)) { throw "missing $pyd - run build.ps1 first" }
New-Item -ItemType Directory -Force -Path $dist | Out-Null

$stage = Join-Path $env:TEMP ("lineforge-pkg-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Force -Path $stage | Out-Null
try {
    Copy-Item $addon (Join-Path $stage 'lineforge') -Recurse -Force
    Get-ChildItem (Join-Path $stage 'lineforge') -Recurse -Include '__pycache__' -Directory -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Copy-Item (Join-Path $root 'LICENSE') (Join-Path $stage 'lineforge\LICENSE') -Force
    Copy-Item (Join-Path $root 'README.md') (Join-Path $stage 'lineforge\README.md') -Force
    if (Test-Path (Join-Path $root 'README.zh.md')) {
        Copy-Item (Join-Path $root 'README.zh.md') (Join-Path $stage 'lineforge\README.zh.md') -Force
    }
    if (Test-Path (Join-Path $root 'CHANGELOG.md')) {
        Copy-Item (Join-Path $root 'CHANGELOG.md') (Join-Path $stage 'lineforge\CHANGELOG.md') -Force
    }

    $zip = Join-Path $dist "lineforge-$Version.zip"
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Compress-Archive -Path (Join-Path $stage 'lineforge') -DestinationPath $zip -CompressionLevel Optimal
    Write-Host ("packaged: {0} ({1:N0} bytes)" -f $zip, (Get-Item $zip).Length) -ForegroundColor Green
} finally {
    if (Test-Path $stage) { Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue }
}
