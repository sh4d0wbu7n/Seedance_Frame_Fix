param(
    [string]$InputVideo,
    [string]$OutputVideo,
    [switch]$Check
)
$ErrorActionPreference = 'Stop'
try {
    $projectRoot = $PSScriptRoot
    $pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
    $rifeExe = Join-Path $projectRoot 'rife-ncnn-vulkan\rife-ncnn-vulkan.exe'
    $rifeModel = Join-Path $projectRoot 'rife-ncnn-vulkan\rife-v4.6'
    foreach ($required in @($pythonExe, $rifeExe, $rifeModel)) {
        if (-not (Test-Path -LiteralPath $required)) { throw "Missing: $required" }
    }
    foreach ($command in @('ffmpeg', 'ffprobe')) {
        if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { throw "$command is missing from PATH." }
    }
    . (Join-Path $projectRoot '.venv\Scripts\Activate.ps1')
    Write-Host ('Using virtual environment: ' + (Join-Path $projectRoot '.venv'))
    . (Join-Path $projectRoot 'launcher_presets.ps1')
    if ($Check) {
        & $pythonExe -c 'import cv2, numpy; print(cv2.__version__, numpy.__version__)'
        if ($LASTEXITCODE -ne 0) { throw 'Python check failed.' }
        Write-Host 'Launcher ready.'
        exit 0
    }
    if (-not $InputVideo) {
        Add-Type -AssemblyName System.Windows.Forms
        $dialog = New-Object System.Windows.Forms.OpenFileDialog
        $dialog.Title = 'Select a video for Seedance Frame Fix'
        $dialog.Filter = 'Videos|*.mp4;*.mov;*.mkv;*.avi;*.webm|All files|*.*'
        try {
            if ($dialog.ShowDialog() -ne 'OK') { exit 0 }
            $InputVideo = $dialog.FileName
        } finally { $dialog.Dispose() }
    }
    $InputVideo = (Resolve-Path -LiteralPath $InputVideo).Path
    $settings = Select-RepairSettings
    if ($null -eq $settings) {
        Write-Host 'Cancelled. No video processed.'
        exit 0
    }
    if (-not $OutputVideo) {
        $folder = Split-Path -Parent $InputVideo
        $stem = [IO.Path]::GetFileNameWithoutExtension($InputVideo)
        $OutputVideo = Join-Path $folder ($stem + '_fixed.mp4')
        $suffix = 2
        while (Test-Path -LiteralPath $OutputVideo) {
            $OutputVideo = Join-Path $folder ($stem + '_fixed_' + $suffix + '.mp4')
            $suffix++
        }
    } elseif (Test-Path -LiteralPath $OutputVideo) {
        throw "Output already exists: $OutputVideo"
    }
    $arguments = @('-u', (Join-Path $projectRoot 'insert_best_frame.py'), $InputVideo, $OutputVideo,
                   '--rife-bin', $rifeExe, '--rife-model', $rifeModel)
    $arguments += $settings.Arguments
    & $pythonExe @arguments
    if ($LASTEXITCODE -ne 0) { throw "Processing failed (exit code $LASTEXITCODE)." }
    if (Test-Path -LiteralPath $OutputVideo) { Write-Host "Result: $OutputVideo" }
    else { Write-Host 'No seams detected; no output file needed.' }
    exit 0
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
