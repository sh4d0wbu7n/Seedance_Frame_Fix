$ErrorActionPreference = 'Stop'
$desktopPath = [Environment]::GetFolderPath('Desktop')
if (-not $desktopPath) { throw 'Desktop-Ordner konnte nicht ermittelt werden.' }
$destination = Join-Path $desktopPath 'Seedance Frame Fix.cmd'
if (Test-Path -LiteralPath $destination) { throw "Launcher existiert bereits: $destination" }
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
