#Requires -Version 7.0
<#
.SYNOPSIS
Tests the logic of the demo's tuning window (scripts/DemoTuning.psm1), without opening it.

.DESCRIPTION
  1. The tool's arguments for a choice: --profile, --<setting>=<value> for the settings set
     (so -5% isn't read as an option), the run options.
  2. The error message read from the tool's stderr (JSON log lines, or an argparse line).
  3. The last choices saved and read back; a missing or broken file gives the defaults.
  4. The real tool (.venv) through Invoke-FoundryTts: profile list and profile check, which make no
     Azure call.
Run it from anywhere: PowerShell 7, Windows, with the tool installed in .venv.
#>
[CmdletBinding()]
param(
    [string] $WorkFolder = (Join-Path ([System.IO.Path]::GetTempPath()) 'demo-tuning-test')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Import-Module (Join-Path $root 'scripts\DemoTuning.psm1') -Force
$failures = 0

function Assert-True([bool] $Condition, [string] $Name) {
    if ($Condition) { Write-Host "PASS  $Name" }
    else { Write-Host "FAIL  $Name" -ForegroundColor Red; $script:failures++ }
}

function Assert-Equal($Expected, $Actual, [string] $Name) {
    $same = ($Expected -join "`u{1F}") -ceq ($Actual -join "`u{1F}")
    if (-not $same) { Write-Host "      expected: $($Expected -join ' | ')`n      actual:   $($Actual -join ' | ')" }
    Assert-True $same $Name
}

if (Test-Path $WorkFolder) { Remove-Item $WorkFolder -Recurse -Force }
New-Item -ItemType Directory -Path $WorkFolder | Out-Null

# 1. Arguments
$choice = New-TuningChoice -Deck 'C:\decks\Contoso overview.pptx' -VoiceProfile 'ava-hd'
Assert-Equal @('--profile', 'ava-hd') (ConvertTo-VoiceArguments -Choice $choice) 'no setting set: the profile only'
$choice.Settings['rate'] = ' -5% '
$choice.Settings['temperature'] = '0.6'
$choice.Settings['style'] = 'narrator'
Assert-Equal @('--profile', 'ava-hd', '--style=narrator', '--rate=-5%', '--temperature=0.6') `
(ConvertTo-VoiceArguments -Choice $choice) 'settings in the = form, trimmed, in the tool''s order'
Assert-Equal @('deck', 'narrate', 'C:\decks\Contoso overview.pptx', '--profile', 'ava-hd', '--style=narrator', '--rate=-5%', '--temperature=0.6', '--auto-advance') `
(ConvertTo-NarrateArguments -Choice $choice) 'narrate: the deck, the settings, auto-advance'
$choice.Video = $true
Assert-True ((ConvertTo-NarrateArguments -Choice $choice) -contains '--video') 'video: --video'
Assert-True (-not ((ConvertTo-NarrateArguments -Choice $choice) -contains '--auto-advance')) 'video: no separate --auto-advance (it implies it)'
$choice.Video = $false
$choice.AutoAdvance = $false
Assert-True (-not ((ConvertTo-NarrateArguments -Choice $choice) -contains '--auto-advance')) 'auto-advance off: not passed'
$empty = New-TuningChoice -Deck 'd.pptx'
Assert-Equal @('deck', 'narrate', 'd.pptx', '--auto-advance') (ConvertTo-NarrateArguments -Choice $empty) 'no profile: the tool''s default'
Assert-Equal '0.6' (Format-SettingValue 0.6) 'a number is shown with a dot'
$french = [cultureinfo]::CurrentCulture
try {
    [cultureinfo]::CurrentCulture = 'fr-FR'
    Assert-Equal '0.6' (Format-SettingValue 0.6) 'a number is shown with a dot, even in fr-FR'
}
finally { [cultureinfo]::CurrentCulture = $french }
$choice.Settings['volume'] = '80'
Assert-True ((ConvertTo-VoiceArguments -Choice $choice) -contains '--volume=80') 'volume: --volume=80'

# 1b. Sliders (issue #31): position -> value, and value -> position.
Assert-Equal '1.2' (ConvertTo-SliderText -Name rate -Position 120) 'rate slider 120: multiplier 1.2'
Assert-Equal '1' (ConvertTo-SliderText -Name rate -Position 100) 'rate slider 100: 1 (normal)'
Assert-Equal '0.55' (ConvertTo-SliderText -Name rate -Position 55) 'rate slider 55: 0.55'
Assert-Equal '+10%' (ConvertTo-SliderText -Name pitch -Position 10) 'pitch slider 10: +10%'
Assert-Equal '-15%' (ConvertTo-SliderText -Name pitch -Position -15) 'pitch slider -15: -15%'
Assert-Equal '0%' (ConvertTo-SliderText -Name pitch -Position 0) 'pitch slider 0: 0% (normal)'
Assert-Equal '80' (ConvertTo-SliderText -Name volume -Position 80) 'volume slider 80: 80'
try {
    [cultureinfo]::CurrentCulture = 'fr-FR'
    Assert-Equal '1.25' (ConvertTo-SliderText -Name rate -Position 125) 'rate slider: a dot, even in fr-FR'
}
finally { [cultureinfo]::CurrentCulture = $french }
$cases = @(
    @('rate', '1.2', 120), @('rate', '-5%', 95), @('rate', '+50%', 150), @('rate', 'slow', 64), @('rate', 'X-Fast', 200),
    @('rate', '3', $null), @('rate', '+1', $null), @('rate', 'faster', $null),
    @('pitch', '+10%', 10), @('pitch', '-20%', -20), @('pitch', 'high', 20), @('pitch', '+2st', $null), @('pitch', '200Hz', $null), @('pitch', '+80%', $null),
    @('volume', '80', 80), @('volume', '-10', 90), @('volume', '-25%', 75), @('volume', 'soft', 40), @('volume', 'default', 100),
    @('volume', '120', $null), @('volume', '+10', $null), @('volume', '', $null)
)
foreach ($case in $cases) {
    $name, $text, $expected = $case
    $actual = ConvertFrom-SliderText -Name $name -Text $text
    Assert-True ($actual -eq $expected) "$name '$text' -> slider $(if ($null -eq $expected) { 'unchanged' } else { $expected })$(if ($actual -ne $expected) { " (got $actual)" })"
}
$ranges = @{ rate = 50..200; pitch = -50..50; volume = 0..100 }
foreach ($name in 'rate', 'pitch', 'volume') {
    $back = foreach ($position in $ranges[$name]) {
        $text = ConvertTo-SliderText -Name $name -Position $position
        $read = ConvertFrom-SliderText -Name $name -Text $text
        if ($read -ne $position) { "$position->$text->$read" }
    }
    Assert-True (-not $back) "${name}: a slider's value moves it back to the same place$(if ($back) { " ($($back -join ', '))" })"
}

# 2. Error messages
$lines = @(
    '{"time": "t", "level": "INFO", "logger": "foundry_tts", "message": "Deck read."}',
    '{"time": "t", "level": "ERROR", "logger": "foundry_tts", "message": "Profile ''x'': rate doesn''t apply."}'
)
Assert-Equal "Profile 'x': rate doesn't apply." (Get-ToolErrorMessage -Lines $lines) 'the last ERROR log line'
Assert-Equal 'foundry-tts profile check: error: argument --rate: expected one argument' `
(Get-ToolErrorMessage -Lines @('usage: foundry-tts profile check [-h]', 'foundry-tts profile check: error: argument --rate: expected one argument')) 'an argparse error: its last line'
Assert-True ($null -eq (Get-ToolErrorMessage -Lines @('{"level": "INFO", "message": "ok"}'))) 'no error: nothing'

# 3. Last choices
$statePath = Join-Path $WorkFolder 'state\tuning.json'
$fresh = Read-TuningChoice -Path $statePath
Assert-True ($fresh.Deck -eq '' -and $fresh.AutoAdvance -and $fresh.SlideShow -and -not $fresh.Video) 'no file: the defaults'
$choice.Settings['instructions'] = 'Calme, posé.'
Save-TuningChoice -Choice $choice -Path $statePath
$back = Read-TuningChoice -Path $statePath
Assert-Equal $choice.Deck $back.Deck 'saved and read back: the deck'
Assert-Equal $choice.Profile $back.Profile 'saved and read back: the profile'
Assert-Equal @($choice.Settings.Values) @($back.Settings.Values) 'saved and read back: the settings, accents kept'
Assert-True ($back.AutoAdvance -eq $false -and $back.Video -eq $false -and $back.SlideShow) 'saved and read back: the run options'
Set-Content -LiteralPath $statePath -Value '{ not json'
$broken = Read-TuningChoice -Path $statePath -WarningVariable warned -WarningAction SilentlyContinue
Assert-True ($broken.Deck -eq '' -and @($warned).Count -eq 1) 'a broken file: a warning and the defaults'

# 4. The real tool, no Azure call
$tool = Join-Path $root '.venv\Scripts\foundry-tts.exe'
$listing = Invoke-FoundryTts -Tool $tool -Root $root -Arguments @('profile', 'list')
Assert-True ($listing.ExitCode -eq 0) 'profile list runs'
$data = $listing.Output -join "`n" | ConvertFrom-Json
Assert-True ($data.default -and @($data.profiles).Count -ge 1) 'profile list: a default and profiles'
$check = Invoke-FoundryTts -Tool $tool -Root $root -Arguments (@('profile', 'check') + (ConvertTo-VoiceArguments -Choice (New-TuningChoice -VoiceProfile $data.default)))
Assert-True ($check.ExitCode -eq 0 -and $null -eq $check.Error) 'profile check of the default profile passes'
$refused = New-TuningChoice -VoiceProfile 'marin-presenter'
$refused.Settings['rate'] = '-5%'
$bad = Invoke-FoundryTts -Tool $tool -Root $root -Arguments (@('profile', 'check') + (ConvertTo-VoiceArguments -Choice $refused))
Assert-True ($bad.ExitCode -eq 1 -and $bad.Error -like "*rate doesn't apply to the openai engine*") 'profile check: a setting the engine refuses, with the reason'
$accented = New-TuningChoice -VoiceProfile 'marin-presenter'
$accented.Settings['instructions'] = 'Calme et posé.'
$utf8 = Invoke-FoundryTts -Tool $tool -Root $root -Arguments (@('profile', 'check') + (ConvertTo-VoiceArguments -Choice $accented))
Assert-Equal 'Calme et posé.' (($utf8.Output -join "`n" | ConvertFrom-Json).settings.instructions) 'accents come back from the tool unchanged'

Remove-Item $WorkFolder -Recurse -Force
if ($failures) {
    Write-Host "$failures check(s) failed." -ForegroundColor Red
    exit 1
}
Write-Host 'All checks passed.'
