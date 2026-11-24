<#
.SYNOPSIS
    Pick a deck, get it back ready to play: narrated, self-running, opened in Slide Show.

.DESCRIPTION
    The demo launcher (docs/demo.md). From anywhere, on Windows with desktop PowerPoint:
      0. Brings the clone to an up-to-date main (scripts/DemoUpdate.psm1): fetches origin,
         switches to main if another branch is checked out, fast-forwards it. Started from a
         linked worktree, or when the code changed, it runs the main clone's launcher instead, so
         the demo always runs the current main. It stops rather than lose uncommitted work, and
         without a network it warns and runs the local main. -NoUpdate skips this step.
      1. Checks the tool is installed (.venv) and the Azure sign-in still gives a token.
      2. Opens the tuning window (scripts/DemoTuning.psm1), filled in with the last run's choices:
         pick the deck, the voice profile and its settings (voice, language, style, rate, pitch,
         temperature, or instructions), and the run options (auto-advance, MP4 video, Slide Show).
         "Listen to a sample" speaks the first narrated slide with those settings; "Save as
         profile…" adds them to foundry-tts.toml; "Narrate" checks them and goes on. With
         -SkipTuning, a file picker asks for the deck instead (unless -Deck is given).
      3. Runs `foundry-tts deck narrate <deck> --auto-advance` (and the chosen settings) from the
         repository's folder, so foundry-tts.toml and .env are found. The source deck is never
         changed; the narrated copy goes to output\<deck name>\<deck name>.narrated.pptx. A rerun
         reuses the audio of the slides whose notes and settings didn't change (no Azure call).
      Every step and every log line of the tool is shown in the console as it comes and kept in
      %LOCALAPPDATA%\foundry-tts-ppt\logs\demo-<yyyyMMdd>.log; a failure ends with "The demo
      stopped: ..." and that file's path (docs/demo.md, "If something goes wrong").
      4. Starts the narrated copy in Slide Show: each slide's narration plays on its own and the
         deck moves on when it ends. After the last slide, PowerPoint shows its black "End of
         slide show" screen until a click or Esc.

.PARAMETER Deck
    The deck (.pptx). It fills the window's deck box; with -SkipTuning, without it, a file picker
    opens.

.PARAMETER VoiceProfile
    A profile from foundry-tts.toml (`foundry-tts --list-profiles`): it is picked in the window, or
    used as is with -SkipTuning. Otherwise the last run's, or the default profile (andrew-hd).

.PARAMETER NoSlideShow
    Make the narrated copy and give its path, without starting the show.

.PARAMETER SkipTuning
    No tuning window: the deck from -Deck or a file picker, the profile as it is, auto-advance on.

.PARAMETER NoUpdate
    Run the code as it is checked out, without switching to or updating main (to rehearse a
    branch on purpose).

.EXAMPLE
    # PowerShell (workstation), from anywhere
    D:\path\to\foundry-tts-ppt\scripts\Start-Demo.ps1

.EXAMPLE
    ./scripts/Start-Demo.ps1 -Deck "$HOME\Documents\Contoso overview.pptx" -VoiceProfile harper-narrator -SkipTuning
#>
[CmdletBinding()]
param(
    [string] $Deck,
    [string] $VoiceProfile,
    [switch] $NoSlideShow,
    [switch] $SkipTuning,
    [switch] $NoUpdate
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# The branch the demo always runs from, and the variable that marks the main clone's launcher as
# already updated (so it doesn't update and restart again).
$MainBranch = 'main'
$UpdatedMarker = 'FOUNDRY_TTS_DEMO_UPDATED'

# ---- 0. Run from an up-to-date main ----------------------------------------------------------
if (-not $NoUpdate -and -not [Environment]::GetEnvironmentVariable($UpdatedMarker)) {
    Import-Module (Join-Path $PSScriptRoot 'DemoUpdate.psm1') -Force
    $here = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    $mainClone = Get-MainCheckout -Root $here
    $update = Update-CloneToMain -Root $mainClone -Branch $MainBranch
    Write-Host $update.Summary
    $elsewhere = -not [string]::Equals($mainClone.TrimEnd('\'), $here.TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)
    if ($elsewhere -or $update.Changed) {
        # This file may be stale (another worktree, or older than the update): run the main clone's.
        $launcher = Join-Path $mainClone 'scripts\Start-Demo.ps1'
        if ($elsewhere) { Write-Host "Started from $here; running the main clone's launcher: $launcher" }
        [Environment]::SetEnvironmentVariable($UpdatedMarker, '1')
        try { & $launcher @PSBoundParameters }
        finally { [Environment]::SetEnvironmentVariable($UpdatedMarker, $null) }
        return
    }
}

# Where Azure AI services tokens come from; the same scope the tool asks DefaultAzureCredential for.
$CognitiveServicesResource = 'https://cognitiveservices.azure.com'
$PowerPointAppPath = 'Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\powerpnt.exe'
# The tuning window's last choices: on this computer only, never in the repository.
$TuningStatePath = Join-Path $env:LOCALAPPDATA 'foundry-tts-ppt\tuning.json'
# One log file a day: the tool's JSON log lines and the launcher's own, on this computer only (they
# name the decks, which may be a customer's).
$LogFolder = Join-Path $env:LOCALAPPDATA 'foundry-tts-ppt\logs'
$LogPath = Join-Path $LogFolder "demo-$(Get-Date -Format 'yyyyMMdd').log"

Import-Module (Join-Path $PSScriptRoot 'DemoTuning.psm1') -Force
Set-DemoLog -Path $LogPath
Write-Host "Logs: the console and $LogPath"

function Select-Deck {
    if ([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA') {
        throw 'The file picker needs PowerShell in STA mode (the default): run it without -MTA, or pass -Deck.'
    }
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = [System.Windows.Forms.OpenFileDialog]::new()
    $dialog.Title = 'Pick the deck to narrate'
    $dialog.Filter = 'PowerPoint decks (*.pptx)|*.pptx'
    try {
        if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { return $null }
        return $dialog.FileName
    }
    finally {
        $dialog.Dispose()
    }
}

function Assert-AzureSignIn {
    if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
        Write-Warning 'The Azure CLI (az) is not installed: the sign-in is not checked before the run.'
        return
    }
    # Only the expiry is asked for, so no token is ever shown.
    $expires = & az account get-access-token --resource $CognitiveServicesResource --query expiresOn -o tsv 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $expires) {
        throw 'The Azure sign-in has expired or is missing: run `az login`, then start the demo again.'
    }
    Write-DemoLog INFO 'Azure sign-in OK.' @{ token_valid_until = "$expires" }
}

# Any failure from here on is logged with where it happened, shown in red with the log file, and
# ends the launcher with exit code 1: never a bare PowerShell error and nothing kept.
try {
    $root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
    $tool = Join-Path $root '.venv\Scripts\foundry-tts.exe'
    if (-not (Test-Path -LiteralPath $tool)) {
        throw "foundry-tts is not installed in $root\.venv: follow docs/getting-started.md, section 2."
    }
    Write-DemoLog INFO 'Demo launcher started.' ([ordered]@{
            root = $root; powershell = "$($PSVersionTable.PSVersion)"; skip_tuning = [bool] $SkipTuning
        })

    # Before the window: its sample calls Azure Speech.
    Assert-AzureSignIn

    if ($SkipTuning) {
        if (-not $Deck) {
            $Deck = Select-Deck
            if (-not $Deck) {
                Write-DemoLog INFO 'No deck picked: nothing to do.'
                return
            }
        }
        $choice = New-TuningChoice -Deck $Deck -VoiceProfile $VoiceProfile
        $choice.SlideShow = -not $NoSlideShow
    }
    else {
        $choice = Read-TuningChoice -Path $TuningStatePath
        if ($Deck) { $choice.Deck = $Deck }
        if ($VoiceProfile) { $choice.Profile = $VoiceProfile }
        if ($NoSlideShow) { $choice.SlideShow = $false }
        $choice = Show-TuningWindow -Tool $tool -Root $root -Choice $choice
        if (-not $choice) {
            Write-DemoLog INFO 'Tuning window closed: nothing to do.'
            return
        }
        Save-TuningChoice -Choice $choice -Path $TuningStatePath
    }
    if (-not (Test-Path -LiteralPath $choice.Deck -PathType Leaf)) { throw "No deck at $($choice.Deck)." }
    $choice.Deck = (Resolve-Path -LiteralPath $choice.Deck).Path
    if ([System.IO.Path]::GetExtension($choice.Deck) -ne '.pptx') { throw "Not a .pptx deck: $($choice.Deck)" }

    Write-DemoLog INFO 'Narrating the deck (the logs follow).' @{ deck = $choice.Deck }
    # stdout is the narrated copy's path; the logs are shown and kept as they come.
    $result = Invoke-FoundryTts -Tool $tool -Root $root -Arguments (ConvertTo-NarrateArguments -Choice $choice)
    if ($result.ExitCode -ne 0) { throw "foundry-tts deck narrate failed: $($result.Error)" }

    $narrated = @($result.Output)[-1]
    if (-not $narrated -or -not (Test-Path -LiteralPath $narrated -PathType Leaf)) {
        throw "foundry-tts didn't give the narrated copy's path (got: '$($result.Output -join ' | ')')."
    }
    Write-DemoLog INFO 'Ready to play.' @{ narrated = $narrated }

    if (-not $choice.SlideShow) { return }
    $powerPoint = (Get-ItemProperty -Path $PowerPointAppPath -ErrorAction SilentlyContinue).'(default)'
    if (-not $powerPoint -or -not (Test-Path -LiteralPath $powerPoint)) {
        throw "Desktop PowerPoint was not found; open the narrated copy yourself: $narrated"
    }
    # /S starts the Slide Show directly.
    Start-Process -FilePath $powerPoint -ArgumentList '/S', "`"$narrated`""
    Write-DemoLog INFO 'Slide Show started.'
}
catch {
    # Where it stopped goes to the file; the console gets the message in red below.
    Write-DemoLog ERROR "The demo stopped: $($_.Exception.Message)" ([ordered]@{
            error_type = $_.Exception.GetType().FullName
            at         = $_.InvocationInfo.PositionMessage
            stack      = $_.ScriptStackTrace
        }) -FileOnly
    Write-Host "`nThe demo stopped: $($_.Exception.Message)`n$(Get-LogHint)" -ForegroundColor Red
    exit 1
}
