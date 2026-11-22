# LineForge — fetch the portable build toolchain (no admin rights needed).
# Downloads w64devkit (GCC/MinGW-w64), CPython 3.13 headers/import-lib and pybind11.
# GPL-2.0-or-later.
[CmdletBinding()]
param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$tc = Join-Path $root 'toolchain'
$dl = Join-Path $tc 'downloads'
New-Item -ItemType Directory -Force -Path $dl, $tc | Out-Null

$w64Dir = Join-Path $tc 'w64devkit'
$pyDir = Join-Path $tc 'py313'
$pbDir = Join-Path $tc 'pybind11'

function Get-File($url, $dest) {
    if ((Test-Path $dest) -and -not $Force) {
        Write-Host "  cached: $(Split-Path -Leaf $dest)" -ForegroundColor DarkGray
        return
    }
    Write-Host "  download: $url" -ForegroundColor DarkGray
    & curl.exe -L --retry 3 --connect-timeout 20 -s -S -o $dest $url
    if ($LASTEXITCODE -ne 0) { throw "download failed: $url" }
}

# --- w64devkit -------------------------------------------------------------
if (-not (Test-Path (Join-Path $w64Dir 'w64devkit\bin\g++.exe')) -or $Force) {
    $sfx = Join-Path $dl 'w64devkit-x64-2.11.0.7z.exe'
    Get-File 'https://github.com/skeeto/w64devkit/releases/download/v2.11.0/w64devkit-x64-2.11.0.7z.exe' $sfx
    New-Item -ItemType Directory -Force -Path $w64Dir | Out-Null
    Write-Host "  extract: w64devkit" -ForegroundColor DarkGray
    $p = Start-Process -FilePath $sfx -ArgumentList @('-y', "-o$w64Dir") -Wait -PassThru -NoNewWindow
    if ($p.ExitCode -ne 0) { throw "w64devkit extraction failed ($($p.ExitCode))" }
}

# --- CPython 3.13 (headers + import library, NuGet distribution) -----------
if (-not (Test-Path (Join-Path $pyDir 'tools\include\Python.h')) -or $Force) {
    $nupkg = Join-Path $dl 'python.3.13.13.nupkg'
    Get-File 'https://api.nuget.org/v3-flatcontainer/python/3.13.13/python.3.13.13.nupkg' $nupkg
    # a nupkg is a zip: extract to a staging dir, then move the tools/ payload
    $stage = Join-Path $dl 'py313-stage'
    if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
    Expand-Archive -LiteralPath $nupkg -DestinationPath $stage -Force
    if (Test-Path $pyDir) { Remove-Item $pyDir -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $pyDir | Out-Null
    Copy-Item (Join-Path $stage 'tools') $pyDir -Recurse -Force
}

# --- pybind11 (headers only) ----------------------------------------------
if (-not (Test-Path (Join-Path $pbDir 'pybind11\include\pybind11\pybind11.h')) -or $Force) {
    $whl = Join-Path $dl 'pybind11-3.1.0-py3-none-any.whl'
    if (-not (Test-Path $whl)) {
        $meta = Invoke-RestMethod -Uri 'https://pypi.org/pypi/pybind11/3.1.0/json' -TimeoutSec 30
        $url = ($meta.urls | Where-Object { $_.packagetype -eq 'bdist_wheel' -and $_.filename -like '*py3-none-any*' } | Select-Object -First 1).url
        if (-not $url) { throw "could not resolve pybind11 wheel url" }
        Get-File $url $whl
    }
    $stage = Join-Path $dl 'pybind11-stage'
    if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
    Expand-Archive -LiteralPath $whl -DestinationPath $stage -Force
    if (Test-Path $pbDir) { Remove-Item $pbDir -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $pbDir | Out-Null
    Copy-Item (Join-Path $stage 'pybind11') $pbDir -Recurse -Force
}

Write-Host "toolchain ready:" -ForegroundColor Green
Write-Host "  $(Join-Path $w64Dir 'w64devkit\bin\g++.exe')"
Write-Host "  $(Join-Path $pyDir 'tools\include\Python.h')"
Write-Host "  $(Join-Path $pbDir 'pybind11\include\pybind11\pybind11.h')"
