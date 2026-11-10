#Requires -Version 7.0
<#
.SYNOPSIS
Turns the speaker notes of a PowerPoint deck into narration with Azure Speech text to speech.

.DESCRIPTION
For each slide that has speaker notes, the script:
  1. reads the notes and builds SSML with the configured voice;
  2. makes one audio file per slide with the Azure Speech text to speech REST API
     (skipped when the notes and voice settings haven't changed since the last run);
  3. saves a narrated copy of the deck: each audio file is embedded, plays automatically,
     and the slide advances when the audio ends;
  4. exports the narrated copy to MP4 (optional).

The original deck is never changed. Needs PowerPoint for Windows (COM automation).

.PARAMETER Presentation
Path of the .pptx deck.

.PARAMETER ConfigPath
Path of the JSON config file. Defaults to notes-to-audio.config.json next to this script.

.PARAMETER OutputFolder
Where the notes, audio, narrated deck and video go. Defaults to "<deck name>-narration" next to the deck.

.PARAMETER NotesOnly
Only extract the notes to slide-NNN.txt files. No Azure calls, no deck changes.

.PARAMETER SkipSynthesis
Use the audio files already in the output folder (slide-NNN.mp3 or .wav) instead of calling Azure.

.PARAMETER SkipVideo
Don't export the MP4, even if video.enabled is true in the config.

.EXAMPLE
./Convert-NotesToAudio.ps1 -Presentation 'C:\Decks\Quarterly review.pptx'
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $Presentation,
    [string] $ConfigPath = (Join-Path $PSScriptRoot 'notes-to-audio.config.json'),
    [string] $OutputFolder,
    [switch] $NotesOnly,
    [switch] $SkipSynthesis,
    [switch] $SkipVideo
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'NotesToAudio.psm1') -Force

$msoTrue = -1
$msoFalse = 0

$deckPath = (Resolve-Path -LiteralPath $Presentation).Path
$deckName = [System.IO.Path]::GetFileNameWithoutExtension($deckPath)
if (-not $OutputFolder) { $OutputFolder = Join-Path (Split-Path -Parent $deckPath) "$deckName-narration" }
New-Item -ItemType Directory -Force -Path $OutputFolder | Out-Null
$OutputFolder = (Resolve-Path -LiteralPath $OutputFolder).Path

$callsAzure = -not $NotesOnly -and -not $SkipSynthesis
$settings = Get-NotesToAudioSettings -Path $ConfigPath -NeedsSpeech $callsAzure
$audioExtension = if ($callsAzure) { Get-AudioExtension -OutputFormat $settings.speech.outputFormat } else { $null }

Write-NotesLog -Message 'Starting.' -Data @{ deck = $deckPath; outputFolder = $OutputFolder; notesOnly = [bool] $NotesOnly; skipSynthesis = [bool] $SkipSynthesis }

# Quit PowerPoint at the end only if this script started it.
$powerPointWasRunning = [bool] (Get-Process -Name POWERPNT -ErrorAction SilentlyContinue)
$app = New-Object -ComObject PowerPoint.Application
$deck = $null
$summary = [System.Collections.Generic.List[object]]::new()
try {
    # Open read-only and without a window; the narrated copy is saved under a new name.
    $deck = $app.Presentations.Open($deckPath, $msoTrue, $msoFalse, $msoFalse)
    $slideWidth = $deck.PageSetup.SlideWidth

    foreach ($slide in $deck.Slides) {
        $number = $slide.SlideIndex
        $stem = Join-Path $OutputFolder ('slide-{0:d3}' -f $number)
        $notes = Get-SlideNotes -Slide $slide
        if ([string]::IsNullOrWhiteSpace($notes)) {
            Write-NotesLog -Message 'No notes on this slide; skipped.' -Data @{ slide = $number }
            $summary.Add([pscustomobject]@{ Slide = $number; Audio = ''; Seconds = $null; Source = 'no notes' })
            continue
        }
        Set-Content -LiteralPath "$stem.txt" -Value $notes -Encoding utf8NoBOM -NoNewline
        if ($NotesOnly) {
            $summary.Add([pscustomobject]@{ Slide = $number; Audio = ''; Seconds = $null; Source = 'notes saved' })
            continue
        }

        if ($SkipSynthesis) {
            $audio = Find-SlideAudio -Stem $stem
            if (-not $audio) { throw "Slide $number has notes but no audio file ($stem.mp3 or .wav) in the output folder." }
            $source = 'existing file'
        } else {
            $ssml = ConvertTo-NotesSsml -Text $notes -Speech $settings.speech
            $audio = "$stem$audioExtension"
            $ssmlPath = "$stem.ssml"
            $unchanged = (Test-Path -LiteralPath $audio) -and (Test-Path -LiteralPath $ssmlPath) -and
                ((Get-Content -LiteralPath $ssmlPath -Raw) -ceq $ssml)
            if ($unchanged) {
                $source = 'reused (notes unchanged)'
            } else {
                Write-NotesLog -Message 'Synthesizing.' -Data @{ slide = $number; characters = $notes.Length; voice = $settings.speech.voice }
                Invoke-SpeechSynthesis -Ssml $ssml -OutFile $audio -Settings $settings
                Set-Content -LiteralPath $ssmlPath -Value $ssml -Encoding utf8NoBOM -NoNewline
                $source = 'Azure Speech'
            }
        }

        $seconds = Add-SlideNarration -Slide $slide -AudioPath $audio -SlideSettings $settings.slides -SlideWidth $slideWidth
        Write-NotesLog -Message 'Narration added.' -Data @{ slide = $number; audio = $audio; seconds = $seconds; source = $source }
        $summary.Add([pscustomobject]@{ Slide = $number; Audio = (Split-Path -Leaf $audio); Seconds = $seconds; Source = $source })
    }

    if (-not $NotesOnly) {
        $narratedPath = Join-Path $OutputFolder "$deckName.narrated.pptx"
        $deck.SaveAs($narratedPath)
        Write-NotesLog -Message 'Narrated deck saved.' -Data @{ path = $narratedPath }

        if ($settings.video.enabled -and -not $SkipVideo) {
            $videoPath = Join-Path $OutputFolder "$deckName.narrated.mp4"
            Write-NotesLog -Message 'Exporting the video; this can take several minutes.' -Data @{ path = $videoPath }
            Export-PresentationVideo -Presentation $deck -Path $videoPath -VideoSettings $settings.video
            Write-NotesLog -Message 'Video exported.' -Data @{ path = $videoPath; bytes = (Get-Item -LiteralPath $videoPath).Length }
        }
    }
} catch {
    Write-NotesLog -Level ERROR -Message 'Failed.' -Data @{ error = $_.Exception.Message }
    throw
} finally {
    if ($deck) { $deck.Close() }
    if (-not $powerPointWasRunning) { $app.Quit() }
    [void] [System.Runtime.InteropServices.Marshal]::ReleaseComObject($app)
}

$summary | Format-Table -AutoSize | Out-String | Write-Information -InformationAction Continue
Write-NotesLog -Message 'Done.' -Data @{ outputFolder = $OutputFolder }
