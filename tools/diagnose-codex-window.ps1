# Diagnose what Windows UI Automation can see in the Codex Desktop window.
# Read-only: uses the standard accessibility API, changes nothing in Codex.
# Output: codex-window-diagnose.txt next to this project (contains on-screen text).
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$root = Split-Path -Parent $PSScriptRoot
$out = Join-Path $root 'codex-window-diagnose.txt'
$lines = New-Object System.Collections.Generic.List[string]
function Log([string]$s) { $lines.Add($s); Write-Host $s }

$procs = Get-Process | Where-Object { $_.Path -like '*\WindowsApps\OpenAI.Codex*' -and $_.MainWindowHandle -ne 0 }
if (-not $procs) { Log 'No Codex Desktop window found. Open Codex and run again.' }

$walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
$script:count = 0
$maxNodes = 4000

function Short([string]$s, [int]$n = 90) {
    if (-not $s) { return '' }
    $s = $s -replace '\s+', ' '
    if ($s.Length -gt $n) { return $s.Substring(0, $n) + '...' } else { return $s }
}

function Dump($el, [int]$depth) {
    if ($script:count -ge $maxNodes -or $depth -gt 40) { return }
    $script:count++
    try {
        $c = $el.Current
        $ct = $c.ControlType.ProgrammaticName -replace 'ControlType\.', ''
        $flags = @()
        $p = $null
        if ($el.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern, [ref]$p)) {
            if ($p.Current.IsSelected) { $flags += 'SELECTED' }
        }
        if ($c.HasKeyboardFocus) { $flags += 'FOCUS' }
        $tag = if ($flags) { ' [' + ($flags -join ',') + ']' } else { '' }
        $aid = if ($c.AutomationId) { ' #' + (Short $c.AutomationId 40) } else { '' }
        $name = Short $c.Name
        if ($name -or $flags -or $depth -lt 6) {
            Log (('  ' * [Math]::Min($depth, 30)) + "$ct$aid '$name'$tag")
        }
    } catch { return }
    $child = $walker.GetFirstChild($el)
    while ($child -ne $null -and $script:count -lt $maxNodes) {
        Dump $child ($depth + 1)
        $child = $walker.GetNextSibling($child)
    }
}

foreach ($p in $procs) {
    Log "=== Process $($p.Id)  $($p.Path)"
    Log "=== Window title: '$($p.MainWindowTitle)'"
    $el = [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle)
    # Chromium builds its accessibility tree on first request; give it a moment.
    $null = $walker.GetFirstChild($el)
    Start-Sleep -Seconds 2
    $script:count = 0
    Dump $el 0
    Log "=== nodes visited: $script:count"
}

$lines | Set-Content -LiteralPath $out -Encoding UTF8
Write-Host ''
Write-Host "Saved to $out"
