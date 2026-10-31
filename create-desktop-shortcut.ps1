# Create (or remove with -Remove) a "Codex Pulse" shortcut on the desktop.
# The shortcut runs pythonw.exe directly, so no console window flashes.
param([switch]$Remove, [string]$Python)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = [Environment]::GetFolderPath('Desktop')
$link = Join-Path $desktop 'Codex Pulse.lnk'

if ($Remove) {
    if (Test-Path -LiteralPath $link) { Remove-Item -LiteralPath $link }
    Write-Host 'Desktop shortcut removed.'
    return
}

function Find-Pythonw {
    $candidates = @()
    if ($Python) { $candidates += $Python }
    # Prefer a base interpreter over a project venv so the shortcut survives venv cleanup.
    $base = & python.exe -c 'import sys; print(sys.base_prefix)' 2>$null
    if ($LASTEXITCODE -eq 0 -and $base) { $candidates += (Join-Path $base.Trim() 'pythonw.exe') }
    $py = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($py) { $candidates += (Join-Path (Split-Path -Parent $py.Source) 'pythonw.exe') }
    foreach ($c in $candidates) {
        if (-not (Test-Path -LiteralPath $c)) { continue }
        $console = Join-Path (Split-Path -Parent $c) 'python.exe'
        & $console -c 'import tkinter' 2>$null
        if ($LASTEXITCODE -eq 0) { return $c }
    }
    throw 'No pythonw.exe with tkinter found. Pass one with -Python <path\to\pythonw.exe>.'
}

$pythonw = Find-Pythonw
$icon = Join-Path $here 'assets\codex-pulse.ico'

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '-m codex_pulse'
$shortcut.WorkingDirectory = $here
$shortcut.Description = 'Codex Pulse: session tokens, cache hit rate and TPS for Codex Desktop'
if (Test-Path -LiteralPath $icon) { $shortcut.IconLocation = "$icon,0" }
$shortcut.Save()
Write-Host "Desktop shortcut created: $link"
Write-Host "  -> $pythonw -m codex_pulse"
