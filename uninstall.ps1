# Stop Codex Pulse and remove Desktop / Startup shortcuts.
# Usage: powershell -ExecutionPolicy Bypass -File .\uninstall.ps1 [-PurgeSettings]
param([switch]$PurgeSettings)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe' OR Name = 'codex-pulse.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq 'codex-pulse.exe' -or $_.CommandLine -match 'codex_pulse' } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped running Codex Pulse (PID $($_.ProcessId))."
    }

& (Join-Path $here 'create-desktop-shortcut.ps1') -Remove
& (Join-Path $here 'install-autostart.ps1') -Remove

if ($PurgeSettings) {
    $cfg = Join-Path $env:APPDATA 'CodexPulse'
    if (Test-Path -LiteralPath $cfg) {
        Remove-Item -LiteralPath $cfg -Recurse -Force
        Write-Host "Removed settings & logs: $cfg"
    }
} else {
    Write-Host "Settings preserved at: $(Join-Path $env:APPDATA 'CodexPulse') (pass -PurgeSettings to remove)."
}
