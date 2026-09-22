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
        if (-not (Test-Path -LiteralPath $required)) { throw "Fehlt: $required" }
    }
    foreach ($command in @('ffmpeg', 'ffprobe')) {
        if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { throw "$command fehlt im PATH." }
    }
    if ($Check) {
        & $pythonExe -c 'import cv2, numpy; print(cv2.__version__, numpy.__version__)'
        if ($LASTEXITCODE -ne 0) { throw 'Python-Pruefung fehlgeschlagen.' }
        Write-Host 'Launcher bereit.'
        exit 0
    }
    if (-not $InputVideo) {
        Add-Type -AssemblyName System.Windows.Forms
        $dialog = New-Object System.Windows.Forms.OpenFileDialog
        $dialog.Title = 'Video fuer Seedance Frame Fix auswaehlen'
        $dialog.Filter = 'Videos|*.mp4;*.mov;*.mkv;*.avi;*.webm|Alle Dateien|*.*'
        try {
            if ($dialog.ShowDialog() -ne 'OK') { exit 0 }
            $InputVideo = $dialog.FileName
        } finally { $dialog.Dispose() }
    }
    $InputVideo = (Resolve-Path -LiteralPath $InputVideo).Path
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
        throw "Ausgabe existiert bereits: $OutputVideo"
    }
    $arguments = @('-u', (Join-Path $projectRoot 'insert_best_frame.py'), $InputVideo, $OutputVideo,
                   '--rife-bin', $rifeExe, '--rife-model', $rifeModel)
    & $pythonExe @arguments
    if ($LASTEXITCODE -ne 0) { throw "Verarbeitung fehlgeschlagen (Exitcode $LASTEXITCODE)." }
    if (Test-Path -LiteralPath $OutputVideo) { Write-Host "Ergebnis: $OutputVideo" }
    else { Write-Host 'Keine Sprungstellen erkannt; keine Ausgabedatei erforderlich.' }
    exit 0
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
