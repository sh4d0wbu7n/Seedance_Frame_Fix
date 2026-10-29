# Run without opening dialogs or processing videos; no Pester dependency required.
$ErrorActionPreference = 'Stop'
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'launcher_presets.ps1')
function Assert-Equal($Actual, $Expected) {
    if ($Actual -cne $Expected) { throw "Expected [$Expected], got [$Actual]" }
}
$presets = @(Get-RepairPresets)
Assert-Equal $presets.Count 6
$expected = @(
    '--threshold 3 --min-relative-jump 0.10 --candidates 7 --crf 14',
    '--threshold 4 --min-relative-jump 0.20 --candidates 7 --crf 14 --no-periodic-recovery',
    '--threshold 3.5 --min-relative-jump 0.15 --candidates 7 --crf 14 --no-periodic-recovery',
    '--threshold 2.5 --min-relative-jump 0.05 --candidates 7 --crf 14 --no-periodic-recovery',
    '--threshold 3 --min-relative-jump 0.10 --candidates 7 --crf 14 --frames 95,119',
    '--threshold 3 --min-relative-jump 0.10 --candidates 7 --crf 14 --frames 95,119'
)
for ($i = 0; $i -lt 6; $i++) {
    Assert-Equal ((Get-RepairArguments $presets[$i] '95, 119') -join ' ') $expected[$i]
}
# Mock console input to cover default, invalid input, manual frames, audio, and cancellation.
function Read-Host {
    param($Prompt)
    if ($script:answers.Count -eq 0) { throw "Unexpected prompt: $Prompt" }
    return $script:answers.Dequeue()
}
function Select-WithAnswers([string[]]$Values) {
    $script:answers = New-Object 'System.Collections.Generic.Queue[string]'
    foreach ($value in $Values) { $script:answers.Enqueue($value) }
    $selection = Select-RepairSettings
    Assert-Equal $script:answers.Count 0
    return $selection
}
$selection = Select-WithAnswers @('')
Assert-Equal ($selection.Arguments -join ' ') $expected[0]
$selection = Select-WithAnswers @('invalid', '4')
Assert-Equal ($selection.Arguments -join ' ') $expected[3]
$selection = Select-WithAnswers @('5', '', '-1', '95, 119')
Assert-Equal ($selection.Arguments -join ' ') $expected[4]
$selection = Select-WithAnswers @('6', '95,119', 'invalid', '2')
Assert-Equal ($selection.Arguments -join ' ') ($expected[5] + ' --no-stretch-audio')
$selection = Select-WithAnswers @('6', '95,119', '')
Assert-Equal ($selection.Arguments -join ' ') $expected[5]
foreach ($sequence in @(@('q'), @('5', 'q'), @('6', '95', 'q'))) {
    Assert-Equal ($null -eq (Select-WithAnswers $sequence)) $true
}
Write-Host 'Launcher preset and interaction checks passed.'
