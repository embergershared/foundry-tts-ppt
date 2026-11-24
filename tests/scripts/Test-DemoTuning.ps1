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
  5. Sample playback through MCI: it plays, loads no WPF (issue #29), and releases the file.
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

# 5. Sample playback (issue #29): MCI plays it, WPF is never loaded (it would switch a DPI-unaware
#    process to DPI-aware and break the window's layout), and stopping releases the file.
function New-ToneWav([string] $Path, [double] $Seconds = 2.0, [int] $SampleRate = 24000) {
    $samples = [int] ($Seconds * $SampleRate)
    $stream = [System.IO.MemoryStream]::new()
    $writer = [System.IO.BinaryWriter]::new($stream)
    $writer.Write([Text.Encoding]::ASCII.GetBytes('RIFF')); $writer.Write([int] (36 + $samples * 2))
    $writer.Write([Text.Encoding]::ASCII.GetBytes('WAVEfmt ')); $writer.Write([int] 16); $writer.Write([int16] 1)
    $writer.Write([int16] 1); $writer.Write([int] $SampleRate); $writer.Write([int] ($SampleRate * 2))
    $writer.Write([int16] 2); $writer.Write([int16] 16)
    $writer.Write([Text.Encoding]::ASCII.GetBytes('data')); $writer.Write([int] ($samples * 2))
    for ($i = 0; $i -lt $samples; $i++) { $writer.Write([int16] (2000 * [math]::Sin(2 * [math]::PI * 440 * $i / $SampleRate))) }
    $writer.Flush()
    [IO.File]::WriteAllBytes($Path, $stream.ToArray())
    $writer.Dispose()
}
$tone = Join-Path $WorkFolder 'sample.wav'
New-ToneWav -Path $tone
Start-SamplePlayback -Path $tone
Assert-Equal 'playing' (Get-SamplePlaybackMode) 'a sample plays'
# PowerShell 7 loads PresentationCore at startup, so the check is on what playing does: a WPF
# MediaPlayer gives the thread a WPF dispatcher (and makes a DPI-unaware process DPI-aware).
$dispatcher = [System.Windows.Threading.Dispatcher]::FromThread([System.Threading.Thread]::CurrentThread)
Assert-True ($null -eq $dispatcher) 'playing a sample starts no WPF media player (no WPF dispatcher on the thread)'
Start-SamplePlayback -Path $tone
Assert-Equal 'playing' (Get-SamplePlaybackMode) 'a second sample replaces the first'
Stop-SamplePlayback
Assert-True ($null -eq (Get-SamplePlaybackMode)) 'stopped: nothing open'
$released = $true
try { [IO.File]::WriteAllBytes($tone, [byte[]] @(0)) } catch { $released = $false }
Assert-True $released 'stopped: the file can be replaced'
Stop-SamplePlayback
Assert-True $true 'stopping with nothing open is harmless'
$missing = $false
try { Start-SamplePlayback -Path (Join-Path $WorkFolder 'nothing.mp3') } catch { $missing = $_.Exception.Message -like 'MCI*failed*' }
Assert-True $missing 'a file that can''t be played: an MCI error (the window then opens the default player)'

Remove-Item $WorkFolder -Recurse -Force
if ($failures) {
    Write-Host "$failures check(s) failed." -ForegroundColor Red
    exit 1
}
Write-Host 'All checks passed.'
