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
  5. The voice picker's filters, on a voice list shaped as voice list --json writes it (voice list
     itself calls Azure, so it isn't run here).
  6. Sample playback through MCI: it plays, loads no WPF (issue #29), and releases the file.
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

# 2b. Logs (issue #40): the tool's JSON lines shown readable in the console and kept in a file.
$info = Format-ToolLogLine -Line '{"time": "2026-11-24T16:08:27.182945+00:00", "level": "INFO", "logger": "foundry_tts.deck_synth", "message": "Sample saved.", "slide": 1, "path": "C:\\out\\Contoso – Final\\sample.mp3", "settings": {}, "seconds": 12.46}'
$clock = [datetimeoffset]::Parse('2026-11-24T16:08:27+00:00').ToLocalTime().ToString('HH:mm:ss')
Assert-Equal "$clock INFO    Sample saved.  slide=1 path=`"C:\out\Contoso – Final\sample.mp3`" settings={} seconds=12.46" $info.Text 'a log line: local time, level, message, then its fields'
Assert-Equal 'INFO' $info.Level 'a log line: its level'
$crash = Format-ToolLogLine -Line '{"time": "2026-11-24T16:08:27+00:00", "level": "ERROR", "logger": "foundry_tts", "message": "Unexpected error: FileNotFoundError: x", "command": "deck sample", "exception": "Traceback (most recent call last):\n  File \"a.py\"\nFileNotFoundError: x"}'
Assert-Equal 'ERROR' $crash.Level 'an error line: ERROR'
Assert-True ($crash.Text -like "*Unexpected error: FileNotFoundError: x  command=`"deck sample`"`n    Traceback (most recent call last):`n      File `"a.py`"`n    FileNotFoundError: x") 'an error line: the traceback indented below it'
Assert-Equal 'Traceback (most recent call last):' (Format-ToolLogLine -Line 'Traceback (most recent call last):').Text 'a line that isn''t JSON: as it is'
Assert-Equal '' (Format-ToolLogLine -Line '{not json').Level 'broken JSON: shown as it is, no level'
Assert-Equal '--:--:-- WARNING Odd.' (Format-ToolLogLine -Line '{"time": "t", "level": "WARNING", "message": "Odd."}').Text 'a time that can''t be read: dashes'
$french = [cultureinfo]::CurrentCulture
try {
    [cultureinfo]::CurrentCulture = 'fr-FR'
    Assert-True ((Format-ToolLogLine -Line '{"time": "t", "level": "INFO", "message": "m", "seconds": 1.5}').Text -like '*seconds=1.5') 'a number field with a dot, even in fr-FR'
}
finally { [cultureinfo]::CurrentCulture = $french }

$logFile = Join-Path $WorkFolder 'logs\demo-test.log'
Set-DemoLog -Path $logFile
Assert-Equal $logFile (Get-DemoLog) 'the log file is set'
Assert-True ((Get-LogHint) -like "*$logFile") 'the error hint names the log file'
Write-DemoLog INFO 'Launcher step.' @{ deck = 'C:\decks\Présentation – Contoso .pptx' } 6>$null
$kept = @(Get-Content -LiteralPath $logFile -Encoding utf8)
$entry = $kept[-1] | ConvertFrom-Json
Assert-True ($entry.logger -eq 'demo' -and $entry.level -eq 'INFO' -and $entry.message -eq 'Launcher step.') 'a launcher line: JSON in the file, logger demo'
Assert-Equal 'C:\decks\Présentation – Contoso .pptx' $entry.deck 'a launcher line: accents and dashes kept in the file'
$shown = Write-DemoLog ERROR 'Stopped.' -FileOnly 6>&1
Assert-True (-not $shown -and (Get-Content -LiteralPath $logFile -Encoding utf8 -Tail 1 | ConvertFrom-Json).message -eq 'Stopped.') 'FileOnly: in the file, not in the console'

# A fake tool (Python, no Azure) that logs on stderr and gives a path with an en dash and an accent
# on stdout: the lines are shown as they come, kept in the file, and the path comes back unchanged.
$fake = Join-Path $WorkFolder 'fake_tool.py'
Set-Content -LiteralPath $fake -Encoding utf8 -Value @'
import json, sys
def log(level, message, **fields):
    print(json.dumps({"time": "2026-11-24T16:00:00+00:00", "level": level, "logger": "fake", "message": message, **fields}, ensure_ascii=False), file=sys.stderr, flush=True)
mode = sys.argv[1]
log("INFO", "Started.", mode=mode)
if mode == "ok":
    print("C:\\out\\Présentation – Contoso\\sample.mp3", flush=True)
    log("INFO", "Done.")
    sys.exit(0)
if mode == "error":
    log("ERROR", "Slide 9 doesn't exist.")
    sys.exit(1)
print("Traceback (most recent call last):", file=sys.stderr)
print("RuntimeError: boom", file=sys.stderr)
sys.exit(3)
'@
$python = Join-Path $root '.venv\Scripts\python.exe'
$lines = [System.Collections.Generic.List[int]]::new()
$ok = Invoke-FoundryTts -Tool $python -Root $root -Arguments @($fake, 'ok') -OnLine { $lines.Add(1) } 6>$null
Assert-True ($ok.ExitCode -eq 0 -and $null -eq $ok.Error) 'fake tool ok: exit 0, no error'
Assert-Equal @('C:\out\Présentation – Contoso\sample.mp3') $ok.Output 'fake tool ok: the stdout path comes back with its accent and en dash'
Assert-Equal 3 $lines.Count 'fake tool ok: OnLine runs for every line (2 logs, 1 output)'
$kept = @(Get-Content -LiteralPath $logFile -Encoding utf8 | ForEach-Object { $_ | ConvertFrom-Json })
Assert-Equal @('Running foundry-tts.', 'Started.', 'Done.', 'foundry-tts done.') @($kept | Select-Object -Last 4 | ForEach-Object message) 'fake tool ok: the run and its logs kept in the file, in order'
$failed = Invoke-FoundryTts -Tool $python -Root $root -Arguments @($fake, 'error') 6>$null
Assert-True ($failed.ExitCode -eq 1 -and $failed.Error -eq "Slide 9 doesn't exist.") 'fake tool error: the tool''s message'
$lastLine = Get-Content -LiteralPath $logFile -Encoding utf8 -Tail 1 | ConvertFrom-Json
Assert-True ($lastLine.level -eq 'ERROR' -and $lastLine.exit_code -eq 1) 'fake tool error: the failure and its exit code logged'
$crashed = Invoke-FoundryTts -Tool $python -Root $root -Arguments @($fake, 'crash') 6>$null
Assert-True ($crashed.ExitCode -eq 3 -and $crashed.Error -eq 'RuntimeError: boom') 'fake tool crash without JSON: its last line'
Assert-True ((Get-Content -LiteralPath $logFile -Encoding utf8 -Raw) -match 'Traceback \(most recent call last\):') 'fake tool crash: the raw lines kept in the file'
Set-DemoLog -Path $null

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
# The real tool's logs reach the log file (issue #40: they used to be dropped).
$realLog = Join-Path $WorkFolder 'logs\real.log'
Set-DemoLog -Path $realLog
$null = Invoke-FoundryTts -Tool $tool -Root $root -Arguments (@('profile', 'check') + (ConvertTo-VoiceArguments -Choice $refused)) 6>$null
$realLines = @(Get-Content -LiteralPath $realLog -Encoding utf8 | ForEach-Object { $_ | ConvertFrom-Json })
Assert-True (@($realLines | Where-Object { $_.logger -like 'foundry_tts*' -and $_.level -eq 'ERROR' -and $_.message -like "*rate doesn't apply*" }).Count -eq 1) 'the real tool''s error line is kept in the log file'
Set-DemoLog -Path $null

# 6. Sample playback (issue #29): MCI plays it, WPF is never loaded (it would switch a DPI-unaware
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

# 5. The voice picker's logic, on a voice list shaped as foundry-tts voice list --json writes it
$listingLines = @(
    '{"voices": [',
    '{"name": "en-GB-SoniaNeural", "display_name": "Sonia", "locale": "en-GB", "gender": "Female", "family": "standard", "model": "Monolingual", "status": "GA", "styles": ["cheerful", "sad"]},',
    '{"name": "en-US-Ava:DragonHDLatestNeural", "display_name": "Ava Dragon HD Latest", "locale": "en-US", "gender": "Female", "family": "Dragon HD", "model": "HDLatest", "status": "GA", "styles": []},',
    '{"name": "en-US-Grant:MAI-Voice-2.1", "display_name": "Grant MAI-Voice-2.1", "locale": "en-US", "gender": "Male", "family": "MAI-Voice", "model": "MAI-Voice-2.1", "status": "Preview", "styles": ["educational", "narrator"]}',
    ']}'
)
$voices = ConvertFrom-VoiceListing -Lines $listingLines
Assert-Equal 3 $voices.Count 'voice list: every voice read'
Assert-Equal 3 (Select-TuningVoice -Voices $voices).Count 'no filter: every voice'
Assert-Equal 3 (Select-TuningVoice -Voices $voices -Language 'All' -Gender 'All' -Family 'All').Count 'All: every voice'
Assert-Equal @('en-US-Ava:DragonHDLatestNeural', 'en-US-Grant:MAI-Voice-2.1') (Select-TuningVoice -Voices $voices -Language 'en-US').name 'language: that locale only'
Assert-Equal @('en-US-Grant:MAI-Voice-2.1') (Select-TuningVoice -Voices $voices -Language 'en-US' -Gender 'Male').name 'filters add up'
Assert-Equal @('en-US-Grant:MAI-Voice-2.1') (Select-TuningVoice -Voices $voices -Search ' NARRATOR ').name 'search: a style, case and spaces ignored'
Assert-Equal @('en-US-Ava:DragonHDLatestNeural') (Select-TuningVoice -Voices $voices -Search 'dragon hd').name 'search: the display name'
Assert-Equal @('en-US-Ava:DragonHDLatestNeural') (Select-TuningVoice -Voices $voices -Family 'Dragon HD').name 'family'
Assert-Equal 0 (Select-TuningVoice -Voices $voices -Search 'nobody').Count 'search with no match: no voice'
Assert-Equal @('All', 'en-GB', 'en-US') (Get-VoiceFilterValues -Voices $voices -Property 'locale') 'filter values: All, then sorted and unique'
Assert-Equal 'en-US-Grant:MAI-Voice-2.1' (Find-TuningVoice -Voices $voices -Name 'en-us-grant:mai-voice-2.1').name 'find a voice: case ignored'
Assert-True ($null -eq (Find-TuningVoice -Voices $voices -Name 'en-US-Nobody')) 'find an unknown voice: none'
Assert-True ($null -eq (Find-TuningVoice -Voices $voices -Name '')) 'find with no name: none'

Remove-Item $WorkFolder -Recurse -Force
if ($failures) {
    Write-Host "$failures check(s) failed." -ForegroundColor Red
    exit 1
}
Write-Host 'All checks passed.'
