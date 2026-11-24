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

function Invoke-FoundryTts {
    <# Runs the tool from the repository's folder (so foundry-tts.toml and .env are found).
       Returns ExitCode, Output (stdout lines) and Error (the error message, when it failed). #>
    param(
        [Parameter(Mandatory)] [string] $Tool,
        [Parameter(Mandatory)] [string] $Root,
        [Parameter(Mandatory)] [string[]] $Arguments
    )
    $errorFile = New-TemporaryFile
    # Python writes to a pipe in the Windows code page unless told UTF-8; a deck name or a setting
    # with an accent would come back garbled.
    $savedUtf8 = $env:PYTHONUTF8
    $savedEncoding = [Console]::OutputEncoding
    $env:PYTHONUTF8 = '1'
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    Push-Location $Root
    try {
        $output = @(& $Tool @Arguments 2> $errorFile.FullName)
        $exitCode = $LASTEXITCODE
        $errorLines = @(Get-Content -LiteralPath $errorFile.FullName -Encoding utf8)
    }
    finally {
        Pop-Location
        $env:PYTHONUTF8 = $savedUtf8
        [Console]::OutputEncoding = $savedEncoding
        Remove-Item -LiteralPath $errorFile.FullName -ErrorAction SilentlyContinue
    }
    $message = if ($exitCode -ne 0) {
        (Get-ToolErrorMessage -Lines $errorLines) ?? "foundry-tts failed (exit $exitCode)."
    }
    [pscustomobject]@{ ExitCode = $exitCode; Output = $output; Error = $message }
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

function Format-SettingValue {
    <# A profile setting as the window shows it: numbers with a dot, whatever the culture. #>
    param($Value)
    if ($null -eq $Value) { return '' }
    [string]::Format([cultureinfo]::InvariantCulture, '{0}', $Value)
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
        Player   = $null
        Result   = $null
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
        Add-Row ((Get-Culture).TextInfo.ToTitleCase($name)) $control
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

    function Invoke-Busy([string] $Message, [string[]] $Arguments) {
        Show-Status $Message
        $form.UseWaitCursor = $true
        $form.Enabled = $false
        [System.Windows.Forms.Application]::DoEvents()
        try { Invoke-FoundryTts -Tool $Tool -Root $Root -Arguments $Arguments }
        finally {
            $form.Enabled = $true
            $form.UseWaitCursor = $false
        }
    }

    function Stop-Sample {
        # The player keeps the file open: it is closed before the next sample replaces it.
        if ($state.Player) {
            $state.Player.Close()
            $state.Player = $null
        }
    }

    function Start-Sample([string] $Path) {
        try {
            Add-Type -AssemblyName PresentationCore
            $state.Player = [System.Windows.Media.MediaPlayer]::new()
            $state.Player.Open([uri]::new($Path))
            $state.Player.Play()
        }
        catch {
            # No in-window player: the default audio app plays it.
            Start-Process -FilePath $Path
        }
    }

    $profileBox.Add_SelectedIndexChanged({ Update-ProfileFields })
    Set-Profiles ($listing.Output -join "`n" | ConvertFrom-Json) $Choice.Profile

    $listen.Add_Click({
            $current = Get-FormChoice
            if (-not (Test-DeckPicked $current)) { return }
            $arguments = @('deck', 'sample', $current.Deck) + (ConvertTo-VoiceArguments -Choice $current)
            Stop-Sample
            $result = Invoke-Busy 'Speaking the first narrated slide…' $arguments
            if ($result.ExitCode -ne 0) { Show-Status $result.Error $true; return }
            $path = @($result.Output)[-1]
            Show-Status "Playing the sample: $path"
            Start-Sample $path
        })

    $save.Add_Click({
            $current = Get-FormChoice
            $name = [Microsoft.VisualBasic.Interaction]::InputBox(
                "Save '$($current.Profile)' with these settings as a new profile in foundry-tts.toml.`n`nName (letters, digits, - and _):",
                'Save as profile', '')
            if (-not $name.Trim()) { return }
            $arguments = @('profile', 'save', $name.Trim()) + (ConvertTo-VoiceArguments -Choice $current)
            $result = Invoke-Busy 'Saving the profile…' $arguments
            if ($result.ExitCode -ne 0) { Show-Status $result.Error $true; return }
            $refreshed = Invoke-FoundryTts -Tool $Tool -Root $Root -Arguments @('profile', 'list')
            if ($refreshed.ExitCode -ne 0) { Show-Status $refreshed.Error $true; return }
            # The new profile holds the settings now: its boxes start empty.
            foreach ($box in $settingBoxes.Values) { $box.Text = '' }
            Set-Profiles ($refreshed.Output -join "`n" | ConvertFrom-Json) $name.Trim()
            Show-Status "Profile '$($name.Trim())' saved in foundry-tts.toml."
        })

    $narrate.Add_Click({
            $current = Get-FormChoice
            if (-not (Test-DeckPicked $current)) { return }
            $arguments = @('profile', 'check') + (ConvertTo-VoiceArguments -Choice $current)
            $result = Invoke-Busy 'Checking the settings…' $arguments
            if ($result.ExitCode -ne 0) { Show-Status $result.Error $true; return }
            $state.Result = $current
            $form.DialogResult = 'OK'
            $form.Close()
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
Get-ToolErrorMessage, Invoke-FoundryTts, Read-TuningChoice, Save-TuningChoice, Format-SettingValue,
ConvertTo-SliderText, ConvertFrom-SliderText, Show-TuningWindow
