# LineForge — package the add-on as an installable Blender zip.
# Thin Windows wrapper around tools/package.py so local builds and CI produce the
# exact same archive. GPL-2.0-or-later.
[CmdletBinding()]
param(
    [string]$Version = ''
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$args_list = @((Join-Path $root 'tools\package.py'))
if ($Version) { $args_list += @('--version', $Version) }

$candidates = @(
    (Join-Path $root 'toolchain\py313\tools\python.exe'),
    (Join-Path ${env:ProgramFiles} 'Blender Foundation\Blender 5.2\5.2\python\bin\python.exe')
)
$python = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $python) {
    $python = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $python) { throw 'no python found (toolchain\py313 or Blender 5.2 python or PATH)' }

& $python @args_list
if ($LASTEXITCODE -ne 0) { throw "packaging failed (exit $LASTEXITCODE)" }
