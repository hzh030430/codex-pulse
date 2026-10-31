# One-click setup for Codex Pulse on Windows:
#   powershell -ExecutionPolicy Bypass -File .\install.ps1
#   powershell -ExecutionPolicy Bypass -File .\install.ps1 -Autostart
param(
    [switch]$Autostart,
    [switch]$NoDesktopShortcut,
    [switch]$NoLaunch,
    [string]$Python
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not $NoDesktopShortcut) {
    $shortcutScript = Join-Path $here 'create-desktop-shortcut.ps1'
    if ($Python) {
        & $shortcutScript -Python $Python
    } else {
        & $shortcutScript
    }
}

if ($Autostart) {
    $autoScript = Join-Path $here 'install-autostart.ps1'
    & $autoScript
}

# Stop any older running Codex Pulse process before launching the fresh build
Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'codex_pulse' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

if (-not $NoLaunch) {
    $startScript = Join-Path $here 'start.ps1'
    & $startScript
}

Write-Host ''
Write-Host 'Codex Pulse is ready! Open Codex Desktop to see the status bar docked at the bottom-right corner.' -ForegroundColor Green
