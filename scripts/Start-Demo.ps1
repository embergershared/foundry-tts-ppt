<#
.SYNOPSIS
    Pick a deck, get it back ready to play: narrated, self-running, opened in Slide Show.

.DESCRIPTION
    The demo launcher (docs/demo.md). From anywhere, on Windows with desktop PowerPoint:
      1. Asks for the deck in a file picker, unless -Deck is given.
      2. Checks the tool is installed (.venv) and the Azure sign-in still gives a token.
      3. Runs `foundry-tts deck narrate <deck> --auto-advance` from the repository's folder, so
         foundry-tts.toml and .env are found. The source deck is never changed; the narrated copy
         goes to output\<deck name>\<deck name>.narrated.pptx. A rerun reuses the audio of the
         slides whose notes didn't change (no Azure call for them).
      4. Starts the narrated copy in Slide Show: each slide's narration plays on its own and the
         deck moves on when it ends. After the last slide, PowerPoint shows its black "End of
         slide show" screen until a click or Esc.

.PARAMETER Deck
    The deck (.pptx). Without it, a file picker opens.

.PARAMETER VoiceProfile
    A profile from foundry-tts.toml (`foundry-tts --list-profiles`); the default profile otherwise.

.PARAMETER NoSlideShow
    Make the narrated copy and give its path, without starting the show.

.EXAMPLE
    # PowerShell (workstation), from anywhere
    D:\path\to\foundry-tts-ppt\scripts\Start-Demo.ps1

.EXAMPLE
    ./scripts/Start-Demo.ps1 -Deck "$HOME\Documents\Contoso overview.pptx" -VoiceProfile harper-narrator
#>
[CmdletBinding()]
param(
    [string] $Deck,
    [string] $VoiceProfile,
    [switch] $NoSlideShow
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Where Azure AI services tokens come from; the same scope the tool asks DefaultAzureCredential for.
$CognitiveServicesResource = 'https://cognitiveservices.azure.com'
$PowerPointAppPath = 'Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\powerpnt.exe'

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

if (-not $Deck) {
    $Deck = Select-Deck
    if (-not $Deck) {
        Write-Host 'No deck picked: nothing to do.'
        return
    }
}
$Deck = (Resolve-Path -LiteralPath $Deck).Path
if ([System.IO.Path]::GetExtension($Deck) -ne '.pptx') { throw "Not a .pptx deck: $Deck" }

Assert-AzureSignIn

$arguments = @('deck', 'narrate', $Deck, '--auto-advance')
if ($VoiceProfile) { $arguments += @('--profile', $VoiceProfile) }

Write-Host "Narrating $([System.IO.Path]::GetFileName($Deck)) (the logs follow)..."
Push-Location $root
try {
    # stdout is the narrated copy's path; the logs (stderr) go to the console as they come.
    $output = & $tool @arguments
    if ($LASTEXITCODE -ne 0) { throw "foundry-tts deck narrate failed (exit $LASTEXITCODE): see the error above." }
}
finally {
    Pop-Location
}

$narrated = @($output)[-1]
if (-not $narrated -or -not (Test-Path -LiteralPath $narrated)) {
    throw "foundry-tts didn't give the narrated copy's path (got: '$output')."
}
Write-Host "Ready to play: $narrated"

if ($NoSlideShow) { return }
$powerPoint = (Get-ItemProperty -Path $PowerPointAppPath -ErrorAction SilentlyContinue).'(default)'
if (-not $powerPoint -or -not (Test-Path $powerPoint)) {
    throw "Desktop PowerPoint was not found; open the narrated copy yourself: $narrated"
}
# /S starts the Slide Show directly.
Start-Process -FilePath $powerPoint -ArgumentList '/S', "`"$narrated`""
