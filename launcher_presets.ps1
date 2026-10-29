# Keep these starting values aligned with README.md.
function Get-RepairPresets {
    @(
        [pscustomobject]@{ Name = 'Standard / continuous camera movement (recommended)'; Description = 'FPV flights, tracking shots or zooms with regular stutters. Uses the tested defaults and recovers weaker periodic peaks.'; Threshold = '3'; RelativeJump = '0.10'; Recover = $true; Manual = $false; Dialogue = $false }
        [pscustomobject]@{ Name = 'Quiet / nearly static shot'; Description = 'Conservative detection to avoid inserting frames for small fluctuations. May miss subtle real jumps.'; Threshold = '4'; RelativeJump = '0.20'; Recover = $false; Manual = $false; Dialogue = $false }
        [pscustomobject]@{ Name = 'Irregular action / pans / lighting changes'; Description = 'Reduces false detections from natural acceleration or brightness changes. Does not recover peaks from a periodic pattern.'; Threshold = '3.5'; RelativeJump = '0.15'; Recover = $false; Manual = $false; Dialogue = $false }
        [pscustomobject]@{ Name = 'Small visible stutters missed by the defaults'; Description = 'More sensitive detection. Use only for visible stutters; inspect the result for unnecessary insertions.'; Threshold = '2.5'; RelativeJump = '0.05'; Recover = $false; Manual = $false; Dialogue = $false }
        [pscustomobject]@{ Name = 'Montage / multiple shots (manual seams)'; Description = 'Prefer processing shots separately. Otherwise enter inspected seam indices; manual indices bypass the cut filter, so exclude intentional cuts.'; Threshold = '3'; RelativeJump = '0.10'; Recover = $true; Manual = $true; Dialogue = $false }
        [pscustomobject]@{ Name = 'Dialogue / lip-synced audio (manual seams)'; Description = 'Enter inspected seam indices. Added frames shift timing; global audio stretching is approximate and cannot guarantee lip sync.'; Threshold = '3'; RelativeJump = '0.10'; Recover = $true; Manual = $true; Dialogue = $true }
    )
}

function Get-RepairArguments {
    param($Preset, [string]$Frames, [switch]$NoStretchAudio)
    $result = @('--threshold', $Preset.Threshold, '--min-relative-jump', $Preset.RelativeJump,
                '--candidates', '7', '--crf', '14')
    if (-not $Preset.Recover) { $result += '--no-periodic-recovery' }
    if ($Preset.Manual) {
        if ($Frames -notmatch '^\s*\d+\s*(,\s*\d+\s*)*$') {
            throw 'Enter comma-separated nonnegative frame indices.'
        }
        $result += @('--frames', ($Frames -replace '\s', ''))
    }
    if ($NoStretchAudio) { $result += '--no-stretch-audio' }
    return $result
}

function Select-RepairSettings {
    $presets = @(Get-RepairPresets)
    Write-Host ''
    Write-Host 'Choose settings for your shot' -ForegroundColor Cyan
    Write-Host 'Press Enter for the tested defaults, or choose another starting point.'
    Write-Host 'Other presets are suggestions, not broadly validated settings.'
    for ($index = 0; $index -lt $presets.Count; $index++) {
        Write-Host ''
        Write-Host ('{0}. {1}' -f ($index + 1), $presets[$index].Name)
        Write-Host ('   ' + $presets[$index].Description)
    }
    Write-Host ''
    while ($true) {
        $choice = (Read-Host 'Preset [1-6, Enter = 1, Q = cancel]').Trim()
        if ($choice -eq 'q') { return $null }
        if (-not $choice) { $choice = '1' }
        if ($choice -match '^[1-6]$') { break }
        Write-Host 'Please enter a number from 1 to 6, or Q.' -ForegroundColor Yellow
    }
    $preset = $presets[[int]$choice - 1]
    $frames = ''
    if ($preset.Manual) {
        Write-Host 'Use zero-based indices of the frame BEFORE each jump, as reported by find_seams.py.'
        Write-Host 'Only enter transitions you inspected; example indices are not preselected.'
        while ($true) {
            $frames = (Read-Host 'Seam indices, comma-separated (Q = cancel)').Trim()
            if ($frames -eq 'q') { return $null }
            if ($frames -match '^\d+\s*(,\s*\d+\s*)*$') { break }
            Write-Host 'Enter at least one nonnegative index, separated by commas.' -ForegroundColor Yellow
        }
    }
    $noStretch = $false
    if ($preset.Dialogue) {
        Write-Host '1. Stretch audio to the new duration (default; approximate synchronization).'
        Write-Host '2. Leave audio unchanged (only if you will retime or replace it separately).'
        while ($true) {
            $audio = (Read-Host 'Audio [1-2, Enter = 1, Q = cancel]').Trim()
            if ($audio -eq 'q') { return $null }
            if ($audio -eq '' -or $audio -eq '1') { break }
            if ($audio -eq '2') { $noStretch = $true; break }
            Write-Host 'Please enter 1, 2, or Q.' -ForegroundColor Yellow
        }
    }
    $parameters = @(Get-RepairArguments -Preset $preset -Frames $frames -NoStretchAudio:$noStretch)
    Write-Host ''
    Write-Host ('Selected: ' + $preset.Name) -ForegroundColor Green
    Write-Host ('Parameters: ' + ($parameters -join ' '))
    return [pscustomobject]@{ Name = $preset.Name; Arguments = $parameters }
}
