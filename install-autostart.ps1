# Add (or remove with -Remove) a Startup-folder shortcut so Codex Pulse runs at logon.
param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$startup = [Environment]::GetFolderPath('Startup')
$link = Join-Path $startup 'Codex Pulse.lnk'

if ($Remove) {
    if (Test-Path -LiteralPath $link) { Remove-Item -LiteralPath $link }
    Write-Host 'Autostart removed.'
    return
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = (Get-Command powershell.exe).Source
$shortcut.Arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + (Join-Path $here 'start.ps1') + '"'
$shortcut.WorkingDirectory = $here
$shortcut.WindowStyle = 7
$shortcut.Save()
Write-Host "Autostart installed: $link"
