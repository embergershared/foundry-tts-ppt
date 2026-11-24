#Requires -Version 7.0
<#
.SYNOPSIS
    The tuning window of the demo launcher (scripts/Start-Demo.ps1), and the logic behind it.

.DESCRIPTION
    The window picks the deck, the voice profile and its settings, and the run options, before
    the deck is narrated. It asks the tool for everything it shows and checks (no voice rule is
    repeated here):
      foundry-tts profile list               the profiles and the settings each voice accepts
      foundry-tts profile check  <settings>  the settings checked by the tool's profile rules
      foundry-tts profile save   <name> ...  the settings saved as a new profile
      foundry-tts deck sample    <deck> ...  one slide spoken, to listen to before the whole deck
      foundry-tts voice list --json          the Azure Speech voices, for the voice picker
    The functions outside Show-TuningWindow don't need a window: tests/scripts/Test-DemoTuning.ps1
    tests them.
#>

Set-StrictMode -Version Latest

# The profile settings the window can override, as the tool's --<name> options, in their order.
$script:SettingNames = @('voice', 'language', 'style', 'rate', 'pitch', 'volume', 'temperature', 'instructions')
# Hints shown in an empty settings box when the profile doesn't set it.
$script:SettingHints = @{
    voice        = 'the profile''s voice'
    language     = 'e.g. en-GB, fr-FR'
    style        = 'e.g. narrator, cheerful'
    rate         = '1 = normal'
    pitch        = '0% = normal'
    volume       = '100 = normal'
    temperature  = '0 to 1, lower is steadier'
    instructions = 'tone and pace, in plain English'
}

# The settings with a slider, like the Foundry playground's Tuning panel. A slider position is an
# integer: rate in hundredths of a multiplier (100 = 1, normal; SSML's documented 0.5 to 2), pitch
# in % (0 = normal; SSML's 0.5 to 1.5 times), volume as SSML's absolute 0 to 100 (100 = normal).
# Named levels map to the equivalents the SSML documentation gives.
$script:Sliders = [ordered]@{
    rate   = @{ Min = 50; Max = 200; Normal = 100; Step = 5; Named = @{ 'x-slow' = 50; slow = 64; medium = 100; fast = 155; 'x-fast' = 200; default = 100 } }
    pitch  = @{ Min = -50; Max = 50; Normal = 0; Step = 5; Named = @{ 'x-low' = -45; low = -20; medium = 0; high = 20; 'x-high' = 45; default = 0 } }
    volume = @{ Min = 0; Max = 100; Normal = 100; Step = 5; Named = @{ silent = 0; 'x-soft' = 20; soft = 40; medium = 60; loud = 80; 'x-loud' = 100; default = 100 } }
}

function ConvertTo-SliderText {
    <# The setting's value for a slider position: rate 1.2, pitch +10%, volume 80. #>
    param([Parameter(Mandatory)] [string] $Name, [Parameter(Mandatory)] [int] $Position)
    $invariant = [cultureinfo]::InvariantCulture
    switch ($Name) {
        'rate' { ($Position / 100).ToString('0.##', $invariant) }
        'pitch' { if ($Position -gt 0) { "+$Position%" } else { "$Position%" } }
        'volume' { "$Position" }
        default { throw "No slider for '$Name'." }
    }
}

function ConvertFrom-SliderText {
    <# The slider position for a value typed in the box, or $null when the slider can't show it
       (semitones, Hz, out of range, not a value): the box keeps it and the tool checks it. #>
    param([Parameter(Mandatory)] [string] $Name, [string] $Text)
    $spec = $script:Sliders[$Name]
    if (-not $spec) { throw "No slider for '$Name'." }
    $value = ([string] $Text).Trim().ToLowerInvariant()
    if (-not $value) { return $null }
    $number = '([+-]?\d+(?:\.\d+)?)'
    $invariant = [cultureinfo]::InvariantCulture
    $position = $null
    if ($spec.Named.ContainsKey($value)) { $position = $spec.Named[$value] }
    elseif ($value -match "^$number%$") {
        $percent = [double]::Parse($Matches[1], $invariant)
        $position = switch ($Name) { 'pitch' { $percent } default { $spec.Normal * (1 + $percent / 100) } }
    }
    elseif ($value -match "^$number$") {
        $parsed = [double]::Parse($Matches[1], $invariant)
        $signed = $Matches[1] -match '^[+-]'
        $position = switch ($Name) {
            'rate' { if ($signed) { $null } else { $parsed * 100 } }
            'volume' { if ($signed) { $spec.Normal + $parsed } else { $parsed } }  # +N/-N: from the normal 100
            default { $null }
        }
    }
    if ($null -eq $position) { return $null }
    $rounded = [int] [math]::Round($position)
    if ($rounded -lt $spec.Min -or $rounded -gt $spec.Max) { return $null }
    $rounded
}

function New-TuningChoice {
    <# The window's choices: the deck, the profile, its overrides (empty: the profile's), the run. #>
    param([string] $Deck = '', [string] $VoiceProfile = '')
    $settings = [ordered]@{}
    foreach ($name in $script:SettingNames) { $settings[$name] = '' }
    [pscustomobject]@{
        Deck        = $Deck
        Profile     = $VoiceProfile
        Settings    = $settings
        AutoAdvance = $true
        Video       = $false
        SlideShow   = $true
    }
}

function ConvertTo-VoiceArguments {
    <# The tool's voice options for the choice: --profile, then --<setting>=<value> for each one set.
       The = form keeps a value such as -5% from being read as an option. #>
    param([Parameter(Mandatory)] $Choice)
    $arguments = @()
    if ($Choice.Profile) { $arguments += @('--profile', $Choice.Profile) }
    foreach ($name in $script:SettingNames) {
        $value = [string] $Choice.Settings[$name]
        if ($value.Trim()) { $arguments += "--$name=$($value.Trim())" }
    }
    , $arguments
}

function ConvertTo-NarrateArguments {
    <# foundry-tts deck narrate's arguments for the choice. #>
    param([Parameter(Mandatory)] $Choice)
    $arguments = @('deck', 'narrate', $Choice.Deck) + (ConvertTo-VoiceArguments -Choice $Choice)
    if ($Choice.Video) { $arguments += '--video' }  # --video turns auto-advance on too
    elseif ($Choice.AutoAdvance) { $arguments += '--auto-advance' }
    , $arguments
}

function Get-ToolErrorMessage {
    <# The message of the last ERROR log line the tool wrote on stderr (JSON lines), or its last
       line when it isn't JSON (an argparse usage error). #>
    param([string[]] $Lines)
    $message = $null
    foreach ($line in @($Lines | Where-Object { $_ -and $_.Trim() })) {
        try {
            $entry = $line | ConvertFrom-Json -ErrorAction Stop
            if ($entry.PSObject.Properties['level'] -and $entry.level -eq 'ERROR') { $message = $entry.message }
        }
        catch {
            $message = $line.Trim()
        }
    }
    $message
}

# ---- Logs ---------------------------------------------------------------------------------------
# The tool writes one JSON object per line on stderr (src/foundry_tts/logs.py). The launcher and the
# window show each line in the console as it comes, readable, and append it unchanged to the log
# file, with the launcher's own steps in the same shape (logger "demo").
$script:LogPath = $null
$script:LogLogger = 'demo'
$script:LevelColors = @{ CRITICAL = 'Red'; ERROR = 'Red'; WARNING = 'Yellow'; DEBUG = 'DarkGray' }
# The fields every line has: shown as the line's head, not as key=value.
$script:LogHeadFields = @('time', 'level', 'logger', 'message', 'exception')
$script:LevelWidth = 7  # WARNING
$script:Utf8 = [System.Text.UTF8Encoding]::new($false)

function Set-DemoLog {
    <# Sends the log lines to that file too (its folder is made); $null: the console only. #>
    param([string] $Path)
    if ($Path) {
        $folder = Split-Path -Parent $Path
        if (-not (Test-Path -LiteralPath $folder)) { New-Item -ItemType Directory -Path $folder -Force | Out-Null }
    }
    $script:LogPath = $Path
}

function Get-DemoLog {
    <# The log file, or $null. #>
    $script:LogPath
}

function Format-LogValue {
    <# A field's value for the console: lists and objects as compact JSON, text with spaces quoted. #>
    param($Value)
    if ($null -eq $Value) { return 'null' }
    if ($Value -is [string]) { return ($Value -match '\s') ? "`"$Value`"" : $Value }
    if ($Value -is [System.Collections.IDictionary] -or ($Value -is [System.Collections.IEnumerable])) {
        return ($Value | ConvertTo-Json -Compress -Depth 6 -WarningAction SilentlyContinue)
    }
    [string]::Format([cultureinfo]::InvariantCulture, '{0}', $Value)
}

function Format-ToolLogLine {
    <# A log line as the console shows it: Level, and Text "HH:mm:ss LEVEL   message  key=value ...",
       the traceback indented below. A line that isn't a JSON object is shown as it is (level ''). #>
    param([AllowEmptyString()] [AllowNull()] [string] $Line)
    $entry = $null
    if ($Line -and $Line.TrimStart().StartsWith('{')) {
        try { $entry = $Line | ConvertFrom-Json -AsHashtable -ErrorAction Stop } catch { $entry = $null }
    }
    if ($entry -isnot [System.Collections.IDictionary] -or -not $entry.Contains('message')) {
        return [pscustomobject]@{ Level = ''; Text = [string] $Line }
    }
    $level = [string] ($entry['level'] ?? 'INFO')
    # ConvertFrom-Json turns an ISO time into a DateTime; another shape stays a string.
    $time = $entry['time']
    $parsed = [datetimeoffset]::MinValue
    $clock = if ($time -is [datetime]) { $time.ToLocalTime().ToString('HH:mm:ss') }
    elseif ($time -and [datetimeoffset]::TryParse([string] $time, [cultureinfo]::InvariantCulture, 'None', [ref] $parsed)) {
        $parsed.ToLocalTime().ToString('HH:mm:ss')
    }
    else { '--:--:--' }
    $fields = foreach ($key in $entry.Keys) {
        if ($script:LogHeadFields -notcontains $key) { "$key=$(Format-LogValue $entry[$key])" }
    }
    $text = "$clock $($level.PadRight($script:LevelWidth)) $($entry['message'])"
    if ($fields) { $text += "  $($fields -join ' ')" }
    if ($entry['exception']) {
        $text += "`n" + ((([string] $entry['exception']).TrimEnd() -split '\r?\n' | ForEach-Object { "    $_" }) -join "`n")
    }
    [pscustomobject]@{ Level = $level; Text = $text }
}

function Write-ToolLogLine {
    <# Shows a log line in the console (errors red, warnings yellow) and appends it to the log file;
       FileOnly: the file only (details the console already says in its own words). #>
    param([AllowEmptyString()] [AllowNull()] [string] $Line, [switch] $FileOnly)
    if (-not $Line) { return }
    if (-not $FileOnly) {
        $formatted = Format-ToolLogLine -Line $Line
        $color = $script:LevelColors[$formatted.Level]
        if ($color) { Write-Host $formatted.Text -ForegroundColor $color } else { Write-Host $formatted.Text }
    }
    if ($script:LogPath) {
        try { [System.IO.File]::AppendAllText($script:LogPath, "$Line`n", $script:Utf8) }
        catch {
            # The console still has it; say once why the file doesn't.
            Write-Warning "The log file $($script:LogPath) can't be written ($($_.Exception.Message)); logging to the console only."
            $script:LogPath = $null
        }
    }
}

function Write-DemoLog {
    <# One of the launcher's own log lines, in the tool's JSON shape (logger "demo"). #>
    param(
        [Parameter(Mandatory)] [ValidateSet('DEBUG', 'INFO', 'WARNING', 'ERROR')] [string] $Level,
        [Parameter(Mandatory)] [string] $Message,
        [System.Collections.IDictionary] $Data = @{},
        [switch] $FileOnly
    )
    $entry = [ordered]@{
        time    = [datetime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.ffffff+00:00', [cultureinfo]::InvariantCulture)
        level   = $Level
        logger  = $script:LogLogger
        message = $Message
    }
    foreach ($key in $Data.Keys) { $entry[$key] = $Data[$key] }
    Write-ToolLogLine -Line ($entry | ConvertTo-Json -Compress -Depth 6 -WarningAction SilentlyContinue) -FileOnly:$FileOnly
}

function Get-LogHint {
    <# Where the details are, for an error message. #>
    if ($script:LogPath) { "Details: the console and $($script:LogPath)" } else { 'Details: the console.' }
}

function Invoke-FoundryTts {
    <# Runs the tool from the repository's folder (so foundry-tts.toml and .env are found). Its
       logs (stderr) are shown and logged as they come; OnLine runs after each line (the window
       repaints there). Returns ExitCode, Output (stdout lines) and Error (the error message, when
       it failed). #>
    param(
        [Parameter(Mandatory)] [string] $Tool,
        [Parameter(Mandatory)] [string] $Root,
        [Parameter(Mandatory)] [string[]] $Arguments,
        [scriptblock] $OnLine
    )
    Write-DemoLog INFO 'Running foundry-tts.' @{ arguments = ($Arguments -join ' ') }
    $output = [System.Collections.Generic.List[string]]::new()
    $errorLines = [System.Collections.Generic.List[string]]::new()
    # Python writes to a pipe in the Windows code page unless told UTF-8; a deck name or a setting
    # with an accent or a dash would come back garbled, and its path not found.
    $savedUtf8 = $env:PYTHONUTF8
    $savedEncoding = [Console]::OutputEncoding
    $env:PYTHONUTF8 = '1'
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $started = [System.Diagnostics.Stopwatch]::StartNew()
    Push-Location -LiteralPath $Root
    try {
        # stderr lines come through as ErrorRecords, in order with stdout, while the tool runs.
        & $Tool @Arguments 2>&1 | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) {
                $line = $_.Exception.Message
                $errorLines.Add($line)
                Write-ToolLogLine -Line $line
            }
            else { $output.Add([string] $_) }
            if ($OnLine) { & $OnLine }
        }
        $exitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
        $env:PYTHONUTF8 = $savedUtf8
        [Console]::OutputEncoding = $savedEncoding
    }
    $done = [ordered]@{
        command = (@($Arguments | Select-Object -First 2) -join ' ')
        seconds = [math]::Round($started.Elapsed.TotalSeconds, 1)
    }
    $message = $null
    if ($exitCode -ne 0) {
        $message = (Get-ToolErrorMessage -Lines $errorLines) ?? "foundry-tts failed (exit $exitCode)."
        $done['exit_code'] = $exitCode
        Write-DemoLog ERROR 'foundry-tts failed.' $done
    }
    else { Write-DemoLog INFO 'foundry-tts done.' $done }
    [pscustomobject]@{ ExitCode = $exitCode; Output = $output.ToArray(); Error = $message }
}

function Read-TuningChoice {
    <# The choices saved by the last run; new ones when there are none. A file that can't be read
       is reported and set aside, so the window still opens. #>
    param([Parameter(Mandatory)] [string] $Path)
    $choice = New-TuningChoice
    if (-not (Test-Path -LiteralPath $Path)) { return $choice }
    try {
        $saved = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json -AsHashtable -ErrorAction Stop
    }
    catch {
        Write-Warning "The last tuning choices in $Path can't be read ($($_.Exception.Message)); starting from the defaults."
        return $choice
    }
    foreach ($key in 'Deck', 'Profile') {
        if ($saved.ContainsKey($key) -and $saved[$key] -is [string]) { $choice.$key = $saved[$key] }
    }
    foreach ($key in 'AutoAdvance', 'Video', 'SlideShow') {
        if ($saved.ContainsKey($key) -and $saved[$key] -is [bool]) { $choice.$key = $saved[$key] }
    }
    if ($saved.ContainsKey('Settings') -and $saved['Settings'] -is [hashtable]) {
        foreach ($name in $script:SettingNames) {
            if ($saved['Settings'].ContainsKey($name)) { $choice.Settings[$name] = [string] $saved['Settings'][$name] }
        }
    }
    $choice
}

function Save-TuningChoice {
    <# Keeps the choices for the next run, in a local file (not in the repository). #>
    param([Parameter(Mandatory)] $Choice, [Parameter(Mandatory)] [string] $Path)
    $folder = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $folder)) { New-Item -ItemType Directory -Path $folder | Out-Null }
    $Choice | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $Path -Encoding utf8
}

# The sample is played with Windows' MCI (winmm.dll), not WPF: loading WPF makes a process that
# hasn't declared its DPI mode DPI-aware, and a window laid out before that then draws its text
# at 150% in its 100% layout, cut off (issue #29). MCI doesn't touch the DPI mode.
$script:SampleAlias = 'foundry_tts_sample'

function Invoke-Mci {
    <# Sends one MCI command; throws with MCI's message when it fails. #>
    param([Parameter(Mandatory)] [string] $Command)
    if (-not ('FoundryTts.Mci' -as [type])) {
        Add-Type -Namespace FoundryTts -Name Mci -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("winmm.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
public static extern int mciSendString(string command, System.Text.StringBuilder result, int length, System.IntPtr callback);
[System.Runtime.InteropServices.DllImport("winmm.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
public static extern bool mciGetErrorString(int error, System.Text.StringBuilder text, int length);
'@
    }
    $result = [System.Text.StringBuilder]::new(256)
    $code = [FoundryTts.Mci]::mciSendString($Command, $result, $result.Capacity, [IntPtr]::Zero)
    if ($code -ne 0) {
        $text = [System.Text.StringBuilder]::new(256)
        [void] [FoundryTts.Mci]::mciGetErrorString($code, $text, $text.Capacity)
        throw "MCI '$Command' failed ($code): $text"
    }
    $result.ToString()
}

function Start-SamplePlayback {
    <# Plays an MP3 or WAV file in the background; a sample still playing is closed first. #>
    param([Parameter(Mandatory)] [string] $Path)
    Stop-SamplePlayback
    $type = if ([System.IO.Path]::GetExtension($Path) -eq '.wav') { 'waveaudio' } else { 'mpegvideo' }
    [void] (Invoke-Mci "open `"$Path`" type $type alias $script:SampleAlias")
    [void] (Invoke-Mci "play $script:SampleAlias")
}

function Stop-SamplePlayback {
    <# Stops the sample and releases its file, so the next sample can replace it. #>
    try { [void] (Invoke-Mci "close $script:SampleAlias") } catch { }  # nothing open: nothing to do
}

function Get-SamplePlaybackMode {
    <# playing, stopped, … or $null when no sample is open (for tests). #>
    try { Invoke-Mci "status $script:SampleAlias mode" } catch { $null }
}

function Format-SettingValue {
    <# A profile setting as the window shows it: numbers with a dot, whatever the culture. #>
    param($Value)
    if ($null -eq $Value) { return '' }
    [string]::Format([cultureinfo]::InvariantCulture, '{0}', $Value)
}

function ConvertFrom-VoiceListing {
    <# The voices of foundry-tts voice list --json's output. #>
    param([string[]] $Lines)
    $data = ($Lines -join "`n") | ConvertFrom-Json
    , @($data.voices)
}

function Select-TuningVoice {
    <# The voices that pass the picker's filters; an empty filter (or 'All') keeps every voice.
       The search text is looked for in the name, display name and styles, case ignored. #>
    param(
        [object[]] $Voices,
        [string] $Search = '',
        [string] $Language = '',
        [string] $Gender = '',
        [string] $Family = ''
    )
    $needle = $Search.Trim()
    , @(foreach ($voice in $Voices) {
            if ($Language -and $Language -ne 'All' -and $voice.locale -ne $Language) { continue }
            if ($Gender -and $Gender -ne 'All' -and $voice.gender -ne $Gender) { continue }
            if ($Family -and $Family -ne 'All' -and $voice.family -ne $Family) { continue }
            if ($needle) {
                $texts = @($voice.name, $voice.display_name) + @($voice.styles)
                if (-not ($texts | Where-Object { $_ -and $_.IndexOf($needle, [StringComparison]::OrdinalIgnoreCase) -ge 0 })) { continue }
            }
            $voice
        })
}

function Get-VoiceFilterValues {
    <# The picker's choices for one filter (locale, gender or family): 'All', then the values the
       voices have, sorted. #>
    param([object[]] $Voices, [Parameter(Mandatory)] [string] $Property)
    $values = @($Voices | ForEach-Object { $_.$Property } | Where-Object { $_ } | Sort-Object -Unique)
    , (@('All') + $values)
}

function Find-TuningVoice {
    <# The voice of that name in the list (case ignored), or $null. #>
    param([object[]] $Voices, [string] $Name)
    if (-not $Name) { return $null }
    foreach ($voice in $Voices) { if ($voice.name -eq $Name) { return $voice } }
    $null
}

function Show-VoicePicker {
    <# A dialog listing the voices, with a search box and filters. Returns the picked voice's name,
       or $null when it is closed. #>
    param(
        [Parameter(Mandatory)] [object[]] $Voices,
        [string] $Current = '',
        [string] $Language = '',
        $Owner = $null
    )
    $dialog = [System.Windows.Forms.Form]::new()
    $dialog.Text = 'Pick a voice'
    $dialog.StartPosition = 'CenterParent'
    # Sizes are given at 96 DPI and scaled to the display, so a 150% display doesn't cut the names.
    $scale = $dialog.DeviceDpi / 96
    function ConvertTo-Pixels([int] $Size) { [int] [Math]::Round($Size * $scale) }
    $dialog.Size = [System.Drawing.Size]::new((ConvertTo-Pixels 1100), (ConvertTo-Pixels 600))
    $dialog.MinimumSize = [System.Drawing.Size]::new((ConvertTo-Pixels 640), (ConvertTo-Pixels 360))
    $dialog.MinimizeBox = $false
    $dialog.Padding = [System.Windows.Forms.Padding]::new(8)

    $filters = [System.Windows.Forms.FlowLayoutPanel]::new()
    $filters.Dock = 'Top'
    $filters.AutoSize = $true
    $filters.WrapContents = $true
    function New-FilterLabel([string] $Text) {
        $label = [System.Windows.Forms.Label]::new()
        $label.Text = $Text
        $label.AutoSize = $true
        $label.Margin = [System.Windows.Forms.Padding]::new(6, 7, 2, 0)
        $label
    }
    function New-FilterBox([string] $Property, [string] $Selected) {
        $box = [System.Windows.Forms.ComboBox]::new()
        $box.DropDownStyle = 'DropDownList'
        $box.Width = ConvertTo-Pixels 130
        foreach ($value in (Get-VoiceFilterValues -Voices $Voices -Property $Property)) { [void] $box.Items.Add($value) }
        $box.SelectedItem = if ($Selected -and $box.Items.Contains($Selected)) { $Selected } else { 'All' }
        $box
    }
    $search = [System.Windows.Forms.TextBox]::new()
    $search.Width = ConvertTo-Pixels 220
    $search.PlaceholderText = 'name or style, e.g. Grant, narrator'
    $currentVoice = Find-TuningVoice -Voices $Voices -Name $Current
    $startLanguage = if ($Language) { $Language } elseif ($currentVoice) { $currentVoice.locale } else { '' }
    $languageBox = New-FilterBox 'locale' $startLanguage
    $genderBox = New-FilterBox 'gender' ''
    $familyBox = New-FilterBox 'family' ''
    $filters.Controls.AddRange(@(
            (New-FilterLabel 'Search'), $search,
            (New-FilterLabel 'Language'), $languageBox,
            (New-FilterLabel 'Gender'), $genderBox,
            (New-FilterLabel 'Family'), $familyBox))

    $list = [System.Windows.Forms.ListView]::new()
    $list.Dock = 'Fill'
    $list.View = 'Details'
    $list.FullRowSelect = $true
    $list.MultiSelect = $false
    $list.HideSelection = $false
    foreach ($column in @(('Voice', 290), ('Gender', 60), ('Family', 125), ('Model', 130), ('Status', 60), ('Styles', 400))) {
        [void] $list.Columns.Add($column[0], (ConvertTo-Pixels $column[1]))
    }

    $bottom = [System.Windows.Forms.FlowLayoutPanel]::new()
    $bottom.Dock = 'Bottom'
    $bottom.AutoSize = $true
    $bottom.FlowDirection = 'RightToLeft'
    $cancel = [System.Windows.Forms.Button]::new()
    $cancel.Text = 'Cancel'
    $cancel.AutoSize = $true
    $cancel.DialogResult = 'Cancel'
    $ok = [System.Windows.Forms.Button]::new()
    $ok.Text = 'Use this voice'
    $ok.AutoSize = $true
    $ok.DialogResult = 'OK'
    $count = [System.Windows.Forms.Label]::new()
    $count.AutoSize = $true
    $count.Margin = [System.Windows.Forms.Padding]::new(0, 8, 12, 0)
    $bottom.Controls.AddRange(@($cancel, $ok, $count))

    # Fill first, then the docked edges, so the list takes the space between them.
    $dialog.Controls.AddRange(@($list, $filters, $bottom))
    $dialog.AcceptButton = $ok
    $dialog.CancelButton = $cancel

    $fill = {
        $shown = Select-TuningVoice -Voices $Voices -Search $search.Text -Language ([string] $languageBox.SelectedItem) `
            -Gender ([string] $genderBox.SelectedItem) -Family ([string] $familyBox.SelectedItem)
        $list.BeginUpdate()
        try {
            $list.Items.Clear()
            foreach ($voice in $shown) {
                $item = [System.Windows.Forms.ListViewItem]::new([string] $voice.name)
                foreach ($text in @($voice.gender, $voice.family, $voice.model, $voice.status, (@($voice.styles) -join ', '))) {
                    [void] $item.SubItems.Add([string] $text)
                }
                $item.Tag = [string] $voice.name
                [void] $list.Items.Add($item)
                if ($voice.name -eq $Current) { $item.Selected = $true }
            }
        }
        finally { $list.EndUpdate() }
        if ($list.SelectedItems.Count) { $list.SelectedItems[0].EnsureVisible() }
        $count.Text = "$($shown.Count) of $($Voices.Count) voices"
        $ok.Enabled = $list.SelectedItems.Count -gt 0
    }
    $search.Add_TextChanged($fill)
    $languageBox.Add_SelectedIndexChanged($fill)
    $genderBox.Add_SelectedIndexChanged($fill)
    $familyBox.Add_SelectedIndexChanged($fill)
    $list.Add_SelectedIndexChanged({ $ok.Enabled = $list.SelectedItems.Count -gt 0 })
    $list.Add_DoubleClick({ if ($list.SelectedItems.Count) { $dialog.DialogResult = 'OK'; $dialog.Close() } })
    & $fill

    try {
        $result = if ($Owner) { $dialog.ShowDialog($Owner) } else { $dialog.ShowDialog() }
        if ($result -eq 'OK' -and $list.SelectedItems.Count) { [string] $list.SelectedItems[0].Tag } else { $null }
    }
    finally { $dialog.Dispose() }
}

function Show-TuningWindow {
    <# Opens the window. Returns the choice when Narrate is clicked, $null when it is closed. #>
    param(
        [Parameter(Mandatory)] [string] $Tool,
        [Parameter(Mandatory)] [string] $Root,
        [Parameter(Mandatory)] $Choice
    )
    if ([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA') {
        throw 'The tuning window needs PowerShell in STA mode (the default): run it without -MTA, or pass -SkipTuning.'
    }
    Add-Type -AssemblyName System.Windows.Forms, System.Drawing, Microsoft.VisualBasic

    $listing = Invoke-FoundryTts -Tool $Tool -Root $Root -Arguments @('profile', 'list')
    if ($listing.ExitCode -ne 0) { throw "The voice profiles can't be read: $($listing.Error)" }
    $state = @{
        Profiles = @{}
        Default  = $null
        Player   = $false
        Result   = $null
        Voices   = $null  # foundry-tts voice list, read the first time Pick… is clicked
    }

    $form = [System.Windows.Forms.Form]::new()
    $form.Text = 'Narrate a deck: tuning'
    $form.StartPosition = 'CenterScreen'
    $form.AutoSize = $true
    $form.AutoSizeMode = 'GrowAndShrink'
    $form.FormBorderStyle = 'FixedDialog'
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.Padding = [System.Windows.Forms.Padding]::new(12)

    $layout = [System.Windows.Forms.TableLayoutPanel]::new()
    $layout.AutoSize = $true
    $layout.ColumnCount = 3
    [void] $layout.ColumnStyles.Add([System.Windows.Forms.ColumnStyle]::new('AutoSize'))
    [void] $layout.ColumnStyles.Add([System.Windows.Forms.ColumnStyle]::new('Absolute', 420))
    [void] $layout.ColumnStyles.Add([System.Windows.Forms.ColumnStyle]::new('AutoSize'))
    $form.Controls.Add($layout)

    function Add-Row([string] $Label, $Control, $Extra = $null, [switch] $Wide) {
        $text = [System.Windows.Forms.Label]::new()
        $text.Text = $Label
        $text.AutoSize = $true
        $text.Anchor = 'Left'
        $text.Margin = [System.Windows.Forms.Padding]::new(0, 6, 8, 0)
        $row = $layout.RowCount
        $layout.RowCount++
        $layout.Controls.Add($text, 0, $row)
        # A text line spans the input and button columns, so it wraps less.
        if (-not $Wide) { $Control.Dock = 'Fill' }
        $layout.Controls.Add($Control, 1, $row)
        if ($Wide) { $layout.SetColumnSpan($Control, 2) }
        if ($Extra) { $layout.Controls.Add($Extra, 2, $row) }
    }

    # Deck
    $deckBox = [System.Windows.Forms.TextBox]::new()
    $deckBox.Text = $Choice.Deck
    $deckBox.PlaceholderText = 'the .pptx to narrate'
    $browse = [System.Windows.Forms.Button]::new()
    $browse.Text = 'Browse…'
    $browse.AutoSize = $true
    $browse.Add_Click({
            $dialog = [System.Windows.Forms.OpenFileDialog]::new()
            $dialog.Title = 'Pick the deck to narrate'
            $dialog.Filter = 'PowerPoint decks (*.pptx)|*.pptx'
            if ($deckBox.Text -and (Test-Path -LiteralPath $deckBox.Text)) {
                $dialog.InitialDirectory = Split-Path -Parent $deckBox.Text
            }
            try { if ($dialog.ShowDialog($form) -eq 'OK') { $deckBox.Text = $dialog.FileName } }
            finally { $dialog.Dispose() }
        })
    Add-Row 'Deck' $deckBox $browse

    # Profile
    $profileBox = [System.Windows.Forms.ComboBox]::new()
    $profileBox.DropDownStyle = 'DropDownList'
    $profileInfo = [System.Windows.Forms.Label]::new()
    $profileInfo.AutoSize = $true
    $profileInfo.MaximumSize = [System.Drawing.Size]::new(520, 0)
    $profileInfo.ForeColor = [System.Drawing.SystemColors]::GrayText
    Add-Row 'Voice profile' $profileBox
    Add-Row '' $profileInfo -Wide

    # Settings: empty means the profile's value, shown greyed in the box. Rate, pitch and volume
    # also get a slider: moving it writes the value in the box; a value typed that it can show
    # moves it; an empty box puts it at the profile's value (or normal).
    $settingBoxes = [ordered]@{}
    $sliders = @{}
    $pickVoice = [System.Windows.Forms.Button]::new()
    $pickVoice.Text = 'Pick…'
    $pickVoice.AutoSize = $true
    $styleHint = [System.Windows.Forms.Label]::new()
    $styleHint.AutoSize = $true
    $styleHint.MaximumSize = [System.Drawing.Size]::new(520, 0)
    $styleHint.ForeColor = [System.Drawing.SystemColors]::GrayText
    foreach ($name in $script:SettingNames) {
        $box = [System.Windows.Forms.TextBox]::new()
        if ($name -eq 'instructions') {
            $box.Multiline = $true
            $box.Height = 48
            $box.ScrollBars = 'Vertical'
        }
        $box.Text = [string] $Choice.Settings[$name]
        $settingBoxes[$name] = $box
        $control = $box
        if ($script:Sliders.Contains($name)) {
            $spec = $script:Sliders[$name]
            $slider = [System.Windows.Forms.TrackBar]::new()
            $slider.Minimum = $spec.Min
            $slider.Maximum = $spec.Max
            $slider.Value = $spec.Normal
            $slider.SmallChange = 1
            $slider.LargeChange = $spec.Step
            $slider.TickStyle = 'None'
            # As tall as its box, so the row lines up with the others.
            $slider.AutoSize = $false
            $slider.Height = $box.PreferredHeight
            $slider.Anchor = 'Left, Right'
            $slider.Tag = $name
            $sliders[$name] = $slider
            $pair = [System.Windows.Forms.TableLayoutPanel]::new()
            $pair.ColumnCount = 2
            [void] $pair.ColumnStyles.Add([System.Windows.Forms.ColumnStyle]::new('Absolute', 120))
            [void] $pair.ColumnStyles.Add([System.Windows.Forms.ColumnStyle]::new('Percent', 100))
            $pair.AutoSize = $true
            $pair.Margin = [System.Windows.Forms.Padding]::new(0)
            $box.Anchor = 'Left, Right'
            $pair.Controls.Add($box, 0, 0)
            $pair.Controls.Add($slider, 1, 0)
            $control = $pair
            $slider.Add_Scroll({
                    param($sender)
                    $settingBoxes[$sender.Tag].Text = ConvertTo-SliderText -Name $sender.Tag -Position $sender.Value
                })
            $box.Tag = $name
            $box.Add_TextChanged({ param($sender) Sync-Slider $sender.Tag })
        }
        $extra = if ($name -eq 'voice') { $pickVoice } else { $null }
        Add-Row ((Get-Culture).TextInfo.ToTitleCase($name)) $control $extra
        if ($name -eq 'style') { Add-Row '' $styleHint -Wide }
    }

    # Run options
    $options = [System.Windows.Forms.FlowLayoutPanel]::new()
    $options.AutoSize = $true
    $autoAdvance = [System.Windows.Forms.CheckBox]::new()
    $autoAdvance.Text = 'Auto-advance'
    $autoAdvance.AutoSize = $true
    $autoAdvance.Checked = $Choice.AutoAdvance
    $video = [System.Windows.Forms.CheckBox]::new()
    $video.Text = 'Export an MP4 video'
    $video.AutoSize = $true
    $video.Checked = $Choice.Video
    $slideShow = [System.Windows.Forms.CheckBox]::new()
    $slideShow.Text = 'Start the Slide Show'
    $slideShow.AutoSize = $true
    $slideShow.Checked = $Choice.SlideShow
    $options.Controls.AddRange(@($autoAdvance, $video, $slideShow))
    Add-Row 'Run' $options
    $video.Add_CheckedChanged({
            # A video needs the slide timings: auto-advance is on with it.
            if ($video.Checked) { $autoAdvance.Checked = $true }
            $autoAdvance.Enabled = -not $video.Checked
        })
    $autoAdvance.Enabled = -not $video.Checked

    # Status line: what the last action did, or why it failed.
    $status = [System.Windows.Forms.Label]::new()
    $status.AutoSize = $true
    $status.MaximumSize = [System.Drawing.Size]::new(520, 0)
    Add-Row '' $status -Wide

    # Buttons
    $buttons = [System.Windows.Forms.FlowLayoutPanel]::new()
    $buttons.AutoSize = $true
    $buttons.FlowDirection = 'RightToLeft'
    $buttons.Dock = 'Fill'
    $cancel = [System.Windows.Forms.Button]::new()
    $cancel.Text = 'Cancel'
    $cancel.AutoSize = $true
    $cancel.DialogResult = 'Cancel'
    $narrate = [System.Windows.Forms.Button]::new()
    $narrate.Text = 'Narrate'
    $narrate.AutoSize = $true
    $save = [System.Windows.Forms.Button]::new()
    $save.Text = 'Save as profile…'
    $save.AutoSize = $true
    $listen = [System.Windows.Forms.Button]::new()
    $listen.Text = 'Listen to a sample'
    $listen.AutoSize = $true
    $buttons.Controls.AddRange(@($cancel, $narrate, $save, $listen))
    $layout.RowCount++
    $layout.Controls.Add($buttons, 0, $layout.RowCount - 1)
    $layout.SetColumnSpan($buttons, 3)
    $form.AcceptButton = $narrate
    $form.CancelButton = $cancel

    function Show-Status([string] $Text, [bool] $IsError = $false) {
        $status.Text = $Text
        $status.ForeColor = if ($IsError) { [System.Drawing.Color]::Firebrick } else { [System.Drawing.SystemColors]::ControlText }
    }

    function Set-Profiles($Data, [string] $Selected) {
        $state.Profiles = @{}
        foreach ($item in $Data.profiles) { $state.Profiles[$item.name] = $item }
        $state.Default = $Data.default
        $profileBox.Items.Clear()
        foreach ($item in $Data.profiles) { [void] $profileBox.Items.Add($item.name) }
        $pick = if ($Selected -and $state.Profiles.ContainsKey($Selected)) { $Selected } else { $Data.default }
        $profileBox.SelectedItem = $pick
    }

    function Update-ProfileFields {
        $item = $state.Profiles[[string] $profileBox.SelectedItem]
        if (-not $item) { return }
        $family = if ($item.family) { ", $($item.family)" } else { '' }
        $marker = if ($item.name -eq $state.Default) { ' (default)' } else { '' }
        $profileInfo.Text = "$($item.engine): $($item.voice)$family$marker"
        foreach ($name in $script:SettingNames) {
            $box = $settingBoxes[$name]
            $box.Enabled = ($name -eq 'voice') -or ($item.applies -contains $name)
            $own = if ($name -eq 'voice') { $item.voice }
            elseif ($item.settings.PSObject.Properties[$name]) { Format-SettingValue $item.settings.$name }
            else { $null }
            $box.PlaceholderText = if ($own) { "profile: $own" } else { $script:SettingHints[$name] }
            if ($sliders.ContainsKey($name)) {
                $sliders[$name].Enabled = $box.Enabled
                Sync-Slider $name
            }
        }
        # The voice list is Azure Speech's: an openai profile's voices aren't in it.
        $pickVoice.Enabled = $item.engine -eq 'speech'
        Update-StyleHint
    }

    function Update-StyleHint {
        # The styles of the voice that will speak (the Voice box, else the profile's), once the
        # voice list has been read.
        $item = $state.Profiles[[string] $profileBox.SelectedItem]
        $styleBox = $settingBoxes['style']
        $styleBox.AutoCompleteMode = 'None'
        if (-not $item -or $item.engine -ne 'speech') { $styleHint.Text = ''; return }
        if ($null -eq $state.Voices) { $styleHint.Text = 'Pick… lists the voices and the styles each one knows.'; return }
        $name = $settingBoxes['voice'].Text.Trim()
        if (-not $name) { $name = $item.voice }
        $voice = Find-TuningVoice -Voices $state.Voices -Name $name
        if (-not $voice) { $styleHint.Text = "$name isn't in the voice list of the resource."; return }
        $styles = @($voice.styles)
        if (-not $styles.Count) { $styleHint.Text = "$($voice.name) has no named styles."; return }
        $styleHint.Text = "Styles of $($voice.name): $($styles -join ', ')"
        $source = [System.Windows.Forms.AutoCompleteStringCollection]::new()
        $source.AddRange([string[]] $styles)
        $styleBox.AutoCompleteCustomSource = $source
        $styleBox.AutoCompleteSource = 'CustomSource'
        $styleBox.AutoCompleteMode = 'SuggestAppend'
    }

    function Sync-Slider([string] $Name) {
        # The box's value, or else the profile's, or else normal; a value the slider can't show
        # (semitones, Hz) leaves it where it is.
        $slider = $sliders[$Name]
        $text = $settingBoxes[$Name].Text
        if (-not $text.Trim()) {
            $item = $state.Profiles[[string] $profileBox.SelectedItem]
            $text = if ($item -and $item.settings.PSObject.Properties[$Name]) { Format-SettingValue $item.settings.$Name } else { '' }
        }
        $position = if ($text.Trim()) { ConvertFrom-SliderText -Name $Name -Text $text } else { $script:Sliders[$Name].Normal }
        if ($null -ne $position -and $slider.Value -ne $position) { $slider.Value = $position }
    }

    function Get-FormChoice {
        $current = New-TuningChoice -Deck $deckBox.Text.Trim() -VoiceProfile ([string] $profileBox.SelectedItem)
        foreach ($name in $script:SettingNames) {
            # A setting the profile's voice doesn't accept isn't sent.
            $box = $settingBoxes[$name]
            $current.Settings[$name] = if ($box.Enabled) { $box.Text.Trim() } else { '' }
        }
        $current.AutoAdvance = $autoAdvance.Checked
        $current.Video = $video.Checked
        $current.SlideShow = $slideShow.Checked
        $current
    }

    function Test-DeckPicked($Current) {
        if (-not $Current.Deck) { Show-Status 'Pick the deck first.' $true; return $false }
        if (-not (Test-Path -LiteralPath $Current.Deck -PathType Leaf)) { Show-Status "No file at $($Current.Deck)." $true; return $false }
        if ([System.IO.Path]::GetExtension($Current.Deck) -ne '.pptx') { Show-Status 'The deck must be a .pptx file.' $true; return $false }
        $true
    }

    function Show-ToolError($Result) {
        # The tool's own message, and where its logs are.
        Show-Status "$($Result.Error)`n$(Get-LogHint)" $true
    }

    function Invoke-WindowAction([string] $Name, [scriptblock] $Action) {
        # A button's work: whatever fails is logged and shown in the status line, and the window
        # stays usable (an exception in a WinForms handler would otherwise be lost or end it).
        Write-DemoLog INFO "Window: $Name."
        try { & $Action }
        catch {
            Write-DemoLog ERROR "Window: $Name failed: $($_.Exception.Message)" ([ordered]@{
                    action     = $Name
                    error_type = $_.Exception.GetType().FullName
                    at         = $_.InvocationInfo.PositionMessage
                    stack      = $_.ScriptStackTrace
                })
            Show-Status "$Name failed: $($_.Exception.Message)`n$(Get-LogHint)" $true
        }
        finally {
            $form.Enabled = $true
            $form.UseWaitCursor = $false
        }
    }

    function Invoke-Busy([string] $Message, [string[]] $Arguments) {
        Show-Status $Message
        $form.UseWaitCursor = $true
        $form.Enabled = $false
        [System.Windows.Forms.Application]::DoEvents()
        # Repaint between log lines, so the window doesn't turn "Not responding" on a long call.
        try { Invoke-FoundryTts -Tool $Tool -Root $Root -Arguments $Arguments -OnLine { [System.Windows.Forms.Application]::DoEvents() } }
        finally {
            $form.Enabled = $true
            $form.UseWaitCursor = $false
        }
    }

    function Stop-Sample {
        # The player keeps the file open: it is closed before the next sample replaces it.
        if ($state.Player) {
            Stop-SamplePlayback
            $state.Player = $false
        }
    }

    function Start-Sample([string] $Path) {
        try {
            Start-SamplePlayback -Path $Path
            $state.Player = $true
        }
        catch {
            # No in-window player: the default audio app plays it.
            Write-DemoLog WARNING 'The sample can''t be played in the window; opening it in the default audio app.' ([ordered]@{
                    path = $Path; error = $_.Exception.Message
                })
            Start-Process -FilePath $Path
        }
    }

    $profileBox.Add_SelectedIndexChanged({ Update-ProfileFields })
    $settingBoxes['voice'].Add_TextChanged({ Update-StyleHint })

    $pickVoice.Add_Click({
            Invoke-WindowAction 'Pick a voice' {
                if ($null -eq $state.Voices) {
                    $result = Invoke-Busy 'Asking Azure Speech for its voices…' @('voice', 'list', '--json')
                    if ($result.ExitCode -ne 0) { Show-ToolError $result; return }
                    $state.Voices = ConvertFrom-VoiceListing -Lines $result.Output
                    Show-Status "$($state.Voices.Count) voices listed."
                }
                $item = $state.Profiles[[string] $profileBox.SelectedItem]
                $current = $settingBoxes['voice'].Text.Trim()
                if (-not $current) { $current = $item.voice }
                $picked = Show-VoicePicker -Voices $state.Voices -Current $current `
                    -Language $settingBoxes['language'].Text.Trim() -Owner $form
                if ($picked) {
                    # The profile's own voice needs no override.
                    $settingBoxes['voice'].Text = if ($picked -eq $item.voice) { '' } else { $picked }
                    Update-StyleHint
                }
            }
        })
    Set-Profiles ($listing.Output -join "`n" | ConvertFrom-Json) $Choice.Profile

    $listen.Add_Click({
            Invoke-WindowAction 'Listen to a sample' {
                $current = Get-FormChoice
                if (-not (Test-DeckPicked $current)) { return }
                $arguments = @('deck', 'sample', $current.Deck) + (ConvertTo-VoiceArguments -Choice $current)
                Stop-Sample
                $result = Invoke-Busy 'Speaking the first narrated slide…' $arguments
                if ($result.ExitCode -ne 0) { Show-ToolError $result; return }
                $path = @($result.Output)[-1]
                if (-not $path -or -not (Test-Path -LiteralPath $path -PathType Leaf)) {
                    throw "foundry-tts didn't give the sample's path (got: '$path')."
                }
                Show-Status "Playing the sample: $path"
                Write-DemoLog INFO 'Playing the sample.' @{ path = $path }
                Start-Sample $path
            }
        })

    $save.Add_Click({
            Invoke-WindowAction 'Save as profile' {
                $current = Get-FormChoice
                $name = [Microsoft.VisualBasic.Interaction]::InputBox(
                    "Save '$($current.Profile)' with these settings as a new profile in foundry-tts.toml.`n`nName (letters, digits, - and _):",
                    'Save as profile', '')
                if (-not $name.Trim()) { return }
                $arguments = @('profile', 'save', $name.Trim()) + (ConvertTo-VoiceArguments -Choice $current)
                $result = Invoke-Busy 'Saving the profile…' $arguments
                if ($result.ExitCode -ne 0) { Show-ToolError $result; return }
                $refreshed = Invoke-Busy 'Reading the profiles…' @('profile', 'list')
                if ($refreshed.ExitCode -ne 0) { Show-ToolError $refreshed; return }
                # The new profile holds the settings now: its boxes start empty.
                foreach ($box in $settingBoxes.Values) { $box.Text = '' }
                Set-Profiles ($refreshed.Output -join "`n" | ConvertFrom-Json) $name.Trim()
                Show-Status "Profile '$($name.Trim())' saved in foundry-tts.toml."
            }
        })

    $narrate.Add_Click({
            Invoke-WindowAction 'Narrate' {
                $current = Get-FormChoice
                if (-not (Test-DeckPicked $current)) { return }
                $arguments = @('profile', 'check') + (ConvertTo-VoiceArguments -Choice $current)
                $result = Invoke-Busy 'Checking the settings…' $arguments
                if ($result.ExitCode -ne 0) { Show-ToolError $result; return }
                $state.Result = $current
                $form.DialogResult = 'OK'
                $form.Close()
            }
        })

    try {
        [void] $form.ShowDialog()
    }
    finally {
        Stop-Sample
        $form.Dispose()
    }
    $state.Result
}

Export-ModuleMember -Function New-TuningChoice, ConvertTo-VoiceArguments, ConvertTo-NarrateArguments,
Get-ToolErrorMessage, Invoke-FoundryTts, Set-DemoLog, Get-DemoLog, Get-LogHint, Format-ToolLogLine,
Write-ToolLogLine, Write-DemoLog, Read-TuningChoice, Save-TuningChoice, Format-SettingValue,
ConvertTo-SliderText, ConvertFrom-SliderText, ConvertFrom-VoiceListing, Select-TuningVoice,
Get-VoiceFilterValues, Find-TuningVoice, Show-VoicePicker, Start-SamplePlayback, Stop-SamplePlayback,
Get-SamplePlaybackMode, Show-TuningWindow
