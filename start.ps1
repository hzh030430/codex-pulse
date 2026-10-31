# Launch Codex Pulse without a console window.
# Usage:  powershell -ExecutionPolicy Bypass -File .\start.ps1
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

$candidates = @()
$pyw = Get-Command pyw.exe -ErrorAction SilentlyContinue
if ($pyw) { $candidates += $pyw.Source }
$python = Get-Command python.exe -ErrorAction SilentlyContinue
if ($python) { $candidates += (Join-Path (Split-Path -Parent $python.Source) 'pythonw.exe') }

$exe = $null
foreach ($c in $candidates) {
    if (-not (Test-Path -LiteralPath $c)) { continue }
    & $c -c 'import tkinter' 2>$null
    if ($LASTEXITCODE -eq 0) { $exe = $c; break }
}
if (-not $exe) { throw 'No windowless Python with tkinter found (need pyw.exe or pythonw.exe).' }

Start-Process -FilePath $exe -ArgumentList '-m', 'codex_pulse' -WorkingDirectory $here -WindowStyle Hidden
Write-Host "Codex Pulse started with $exe"
