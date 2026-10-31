@echo off
rem Double-click to inspect what UI Automation can read from the Codex window.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0diagnose-codex-window.ps1"
echo.
pause
