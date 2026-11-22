# LineForge — build the native core for Blender 5.2 (CPython 3.13 / x64).
# Uses the portable w64devkit MinGW-w64 toolchain (no admin rights required).
# GPL-2.0-or-later.
[CmdletBinding()]
param(
    [switch]$Clean,
    [switch]$NoCopy,
    [string]$Gxx = ''
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$buildDir = Join-Path $root 'build'
$objDir = Join-Path $buildDir 'obj'
$pyRoot = Join-Path $root 'toolchain\py313\tools'
$pbRoot = Join-Path $root 'toolchain\pybind11\pybind11'
$outDll = Join-Path $buildDir 'win64\lineforge_core.pyd'
$addonBin = Join-Path $root 'addon\lineforge\bin\win64'

if ($Clean -and (Test-Path $buildDir)) {
    Remove-Item $buildDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $objDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $buildDir 'win64') | Out-Null
New-Item -ItemType Directory -Force -Path $addonBin | Out-Null

# --- toolchain -------------------------------------------------------------
if (-not $Gxx) {
    $local = Join-Path $root 'toolchain\w64devkit\w64devkit\bin\g++.exe'
    if (Test-Path $local) { $Gxx = $local }
}
if (-not $Gxx) {
    $cmd = Get-Command g++.exe -ErrorAction SilentlyContinue
    if ($cmd) { $Gxx = $cmd.Source }
}
if (-not $Gxx -or -not (Test-Path $Gxx)) {
    throw "g++ not found. Run tools\get-toolchain.ps1 (downloads w64devkit) or pass -Gxx <path>."
}

$pyInc = Join-Path $pyRoot 'include'
$pyLib = Join-Path $pyRoot 'libs\python313.lib'
if (-not (Test-Path (Join-Path $pyInc 'Python.h'))) { throw "Python headers not found: $pyInc" }
if (-not (Test-Path $pyLib)) { throw "python313.lib not found: $pyLib" }
$pbInc = Join-Path $pbRoot 'include'
if (-not (Test-Path (Join-Path $pbInc 'pybind11\pybind11.h'))) { throw "pybind11 headers not found: $pbInc" }

Write-Host "== LineForge build ==" -ForegroundColor Cyan
Write-Host "  g++    : $Gxx"
Write-Host "  python : $pyInc"
Write-Host "  pybind : $pbInc"

$common = @(
    '-std=c++17', '-O2', '-DNDEBUG', '-D_hypot=hypot',
    "-I$pyInc", "-I$pbInc", "-I$root\src"
)
$sources = @("$root\src\core.cpp", "$root\src\module.cpp")
foreach ($f in $sources) { if (-not (Test-Path $f)) { throw "missing source: $f" } }

$objs = @()
foreach ($f in $sources) {
    $name = [IO.Path]::GetFileNameWithoutExtension($f) + '.o'
    $obj = Join-Path $objDir $name
    Write-Host "  cc $name" -ForegroundColor DarkGray
    & $Gxx @common '-c' $f '-o' $obj
    if ($LASTEXITCODE -ne 0) { throw "compile failed: $f" }
    $objs += $obj
}

Write-Host "  link lineforge_core.pyd" -ForegroundColor DarkGray
& $Gxx '-shared' '-o' $outDll @objs "-L$(Join-Path $pyRoot 'libs')" '-lpython313' '-static' '-Wl,--exclude-libs,ALL'
if ($LASTEXITCODE -ne 0) { throw "link failed" }
if (-not (Test-Path $outDll)) { throw "build produced no output: $outDll" }

$size = (Get-Item $outDll).Length
Write-Host ("  ok: {0} ({1:N0} bytes)" -f $outDll, $size) -ForegroundColor Green

if (-not $NoCopy) {
    Copy-Item $outDll (Join-Path $addonBin 'lineforge_core.pyd') -Force
    Write-Host "  copied -> $(Join-Path $addonBin 'lineforge_core.pyd')" -ForegroundColor Green
}
