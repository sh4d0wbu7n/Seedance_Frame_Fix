$ErrorActionPreference = 'Stop'
$desktopPath = [Environment]::GetFolderPath('Desktop')
if (-not $desktopPath) { throw 'Could not locate the Desktop directory.' }
$destination = Join-Path $desktopPath 'Seedance Frame Fix.cmd'
if (Test-Path -LiteralPath $destination) { throw "Launcher already exists: $destination" }
$launcherPath = Join-Path $PSScriptRoot 'launch.ps1'
$content = @"
@echo off
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "$launcherPath" %*
set "result=%errorlevel%"
echo.
pause
exit /b %result%
"@
Set-Content -LiteralPath $destination -Value $content -Encoding Default
Write-Output $destination
