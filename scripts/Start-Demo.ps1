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

Import-Module (Join-Path $PSScriptRoot 'DemoTuning.psm1') -Force

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
    Write-Host "Azure sign-in OK (token valid until $expires)."
}

$root = Resolve-Path (Join-Path $PSScriptRoot '..')
$tool = Join-Path $root '.venv\Scripts\foundry-tts.exe'
if (-not (Test-Path $tool)) {
    throw "foundry-tts is not installed in $root\.venv: follow docs/getting-started.md, section 2."
}

# Before the window: its sample calls Azure Speech.
Assert-AzureSignIn

if ($SkipTuning) {
    if (-not $Deck) {
        $Deck = Select-Deck
        if (-not $Deck) {
            Write-Host 'No deck picked: nothing to do.'
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
        Write-Host 'Tuning window closed: nothing to do.'
        return
    }
    Save-TuningChoice -Choice $choice -Path $TuningStatePath
}
$choice.Deck = (Resolve-Path -LiteralPath $choice.Deck).Path
if ([System.IO.Path]::GetExtension($choice.Deck) -ne '.pptx') { throw "Not a .pptx deck: $($choice.Deck)" }

$arguments = ConvertTo-NarrateArguments -Choice $choice

Write-Host "Narrating $([System.IO.Path]::GetFileName($choice.Deck)) (the logs follow)..."
Write-Host "foundry-tts $($arguments -join ' ')"
$savedUtf8 = $env:PYTHONUTF8
$env:PYTHONUTF8 = '1'  # the copy's path on stdout stays readable if it has accents
Push-Location $root
try {
    # stdout is the narrated copy's path; the logs (stderr) go to the console as they come.
    $output = & $tool @arguments
    if ($LASTEXITCODE -ne 0) { throw "foundry-tts deck narrate failed (exit $LASTEXITCODE): see the error above." }
}
finally {
    Pop-Location
    $env:PYTHONUTF8 = $savedUtf8
}

$narrated = @($output)[-1]
if (-not $narrated -or -not (Test-Path -LiteralPath $narrated)) {
    throw "foundry-tts didn't give the narrated copy's path (got: '$output')."
}
Write-Host "Ready to play: $narrated"

if (-not $choice.SlideShow) { return }
$powerPoint = (Get-ItemProperty -Path $PowerPointAppPath -ErrorAction SilentlyContinue).'(default)'
if (-not $powerPoint -or -not (Test-Path $powerPoint)) {
    throw "Desktop PowerPoint was not found; open the narrated copy yourself: $narrated"
}
# /S starts the Slide Show directly.
Start-Process -FilePath $powerPoint -ArgumentList '/S', "`"$narrated`""
