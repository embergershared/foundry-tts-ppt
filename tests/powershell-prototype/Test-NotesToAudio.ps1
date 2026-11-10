#Requires -Version 7.0
<#
.SYNOPSIS
Tests the parts of Convert-NotesToAudio.ps1 that don't need Azure.

.DESCRIPTION
  1. SSML building: XML escaping, paragraph pauses, optional rate, audio extensions.
  2. A 3-slide test deck is made with PowerPoint (notes on slides 1 and 3 only).
  3. -NotesOnly extracts the notes of slides 1 and 3, and nothing for slide 2.
  4. -SkipSynthesis with local tone WAV files: the narrated deck has one audio shape on
     slides 1 and 3, slide timings match the audio, and the MP4 is exported.
  5. A second run gives the same result (no duplicate audio shapes).
Azure Speech itself is not called. Needs PowerPoint for Windows.
#>
[CmdletBinding()]
param(
    [string] $WorkFolder = (Join-Path ([System.IO.Path]::GetTempPath()) 'notes-to-audio-test')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\src\powershell-prototype')).Path
$script = Join-Path $root 'Convert-NotesToAudio.ps1'
Import-Module (Join-Path $root 'NotesToAudio.psm1') -Force

$msoTrue = -1
$msoFalse = 0
$ppLayoutText = 2
$toneSeconds = 2.0
$failures = 0

function Assert-True([bool] $Condition, [string] $Name) {
    if ($Condition) { Write-Host "PASS  $Name" }
    else { Write-Host "FAIL  $Name" -ForegroundColor Red; $script:failures++ }
}

function New-ToneWav([string] $Path, [double] $Seconds, [int] $SampleRate = 24000) {
    $samples = [int] ($Seconds * $SampleRate)
    $dataBytes = $samples * 2
    $stream = [System.IO.MemoryStream]::new()
    $writer = [System.IO.BinaryWriter]::new($stream)
    $ascii = [System.Text.Encoding]::ASCII
    $writer.Write($ascii.GetBytes('RIFF')); $writer.Write([int] (36 + $dataBytes)); $writer.Write($ascii.GetBytes('WAVE'))
    $writer.Write($ascii.GetBytes('fmt ')); $writer.Write([int] 16); $writer.Write([int16] 1); $writer.Write([int16] 1)
    $writer.Write([int] $SampleRate); $writer.Write([int] ($SampleRate * 2)); $writer.Write([int16] 2); $writer.Write([int16] 16)
    $writer.Write($ascii.GetBytes('data')); $writer.Write([int] $dataBytes)
    for ($i = 0; $i -lt $samples; $i++) {
        $writer.Write([int16] ([math]::Sin(2 * [math]::PI * 440 * $i / $SampleRate) * 3000))
    }
    $writer.Flush()
    [System.IO.File]::WriteAllBytes($Path, $stream.ToArray())
}

function Get-NotesBody($Slide) {
    foreach ($shape in $Slide.NotesPage.Shapes.Placeholders) {
        if ($shape.PlaceholderFormat.Type -eq 2) { return $shape }
    }
    throw 'No notes body placeholder.'
}

# --- 1. SSML building -------------------------------------------------------------------------
$speech = [pscustomobject]@{ voice = 'en-US-Harper:MAI-Voice-2.1'; language = 'en-US'; style = ''; rate = ''; paragraphBreakMs = 400 }
$ssml = ConvertTo-NotesSsml -Text "Sales & margin <up>`r`rSecond`vline" -Speech $speech
Assert-True ($ssml -like '*Sales &amp; margin &lt;up&gt;*') 'SSML escapes &, < and >'
Assert-True ($ssml -like '*<break time="400ms"/> Second line*') 'SSML puts a pause between paragraphs and joins line breaks'
Assert-True ($ssml -like '*<voice name="en-US-Harper:MAI-Voice-2.1">*') 'SSML uses the configured voice'
Assert-True ($ssml -notlike '*prosody*' -and $ssml -notlike '*express-as*') 'SSML has no prosody or style when none is set'
$parsed = $false; try { [xml] $null = $ssml; $parsed = $true } catch { }
Assert-True $parsed 'SSML is well-formed XML'
$speech.rate = '+10%'
$speech.style = 'narrator'
$styled = ConvertTo-NotesSsml -Text 'Hi' -Speech $speech
Assert-True ($styled -like '*<mstts:express-as style="narrator"><prosody rate="+10%">Hi</prosody></mstts:express-as>*') 'SSML applies the configured style and rate'
$parsed = $false; try { [xml] $null = $styled; $parsed = $true } catch { }
Assert-True $parsed 'Styled SSML is well-formed XML'
Assert-True ((Get-AudioExtension 'audio-24khz-96kbitrate-mono-mp3') -eq '.mp3') 'MP3 format maps to .mp3'
Assert-True ((Get-AudioExtension 'riff-24khz-16bit-mono-pcm') -eq '.wav') 'RIFF format maps to .wav'
$threw = $false; try { Get-AudioExtension 'ogg-24khz-16bit-mono-opus' | Out-Null } catch { $threw = $true }
Assert-True $threw 'Unsupported format fails loudly'

# --- 2. Test deck --------------------------------------------------------------------------------
if (Test-Path $WorkFolder) { Remove-Item $WorkFolder -Recurse -Force }
New-Item -ItemType Directory -Path $WorkFolder | Out-Null
$deckPath = Join-Path $WorkFolder 'Test deck.pptx'
$outFolder = Join-Path $WorkFolder 'out'
$configPath = Join-Path $WorkFolder 'test.config.json'

$config = Get-Content (Join-Path $root 'notes-to-audio.config.json') -Raw | ConvertFrom-Json
$config.video.verticalResolution = 480
$config.video.pollSeconds = 1
$config.video.timeoutMinutes = 10
$config | ConvertTo-Json -Depth 5 | Set-Content $configPath

$notesBySlide = @{ 1 = "Welcome to the review.`rThis is the second paragraph."; 3 = 'Thanks for listening.' }
if (Get-Process -Name POWERPNT -ErrorAction SilentlyContinue) {
    throw 'Close PowerPoint before running the tests: they start and quit their own PowerPoint.'
}
$app = New-Object -ComObject PowerPoint.Application
$deck = $app.Presentations.Add($msoFalse)
foreach ($n in 1..3) {
    $slide = $deck.Slides.Add($n, $ppLayoutText)
    $slide.Shapes.Item(1).TextFrame.TextRange.Text = "Slide $n"
    if ($notesBySlide.ContainsKey($n)) { (Get-NotesBody $slide).TextFrame.TextRange.Text = $notesBySlide[$n] }
}
$deck.SaveAs($deckPath)
$deck.Close()
$originalHash = (Get-FileHash $deckPath).Hash

# --- 3. -NotesOnly -------------------------------------------------------------------------------
& $script -Presentation $deckPath -ConfigPath $configPath -OutputFolder $outFolder -NotesOnly -InformationAction SilentlyContinue
Assert-True ((Get-Content (Join-Path $outFolder 'slide-001.txt') -Raw) -eq $notesBySlide[1]) 'NotesOnly saves slide 1 notes'
Assert-True (-not (Test-Path (Join-Path $outFolder 'slide-002.txt'))) 'NotesOnly skips slide 2 (no notes)'
Assert-True ((Get-Content (Join-Path $outFolder 'slide-003.txt') -Raw) -eq $notesBySlide[3]) 'NotesOnly saves slide 3 notes'
Assert-True (-not (Test-Path (Join-Path $outFolder 'Test deck.narrated.pptx'))) 'NotesOnly saves no deck'

# --- 4 and 5. -SkipSynthesis with local audio, run twice ------------------------------------------
New-ToneWav (Join-Path $outFolder 'slide-001.wav') $toneSeconds
New-ToneWav (Join-Path $outFolder 'slide-003.wav') $toneSeconds
$expectedSeconds = [math]::Ceiling($toneSeconds) + $config.slides.paddingSeconds

foreach ($run in 1..2) {
    & $script -Presentation $deckPath -ConfigPath $configPath -OutputFolder $outFolder -SkipSynthesis -InformationAction SilentlyContinue
    $narrated = $app.Presentations.Open((Join-Path $outFolder 'Test deck.narrated.pptx'), $msoTrue, $msoFalse, $msoFalse)
    foreach ($n in 1..3) {
        $slide = $narrated.Slides.Item($n)
        $audioShapes = @($slide.Shapes | Where-Object { $_.Name -eq $config.slides.audioShapeName })
        if ($notesBySlide.ContainsKey($n)) {
            Assert-True ($audioShapes.Count -eq 1) "Run ${run}: slide $n has one audio shape"
            Assert-True ($audioShapes[0].AnimationSettings.PlaySettings.PlayOnEntry -eq $msoTrue) "Run ${run}: slide $n audio plays automatically"
            Assert-True ($audioShapes[0].Left -ge $narrated.PageSetup.SlideWidth) "Run ${run}: slide $n audio is off the visible slide"
            Assert-True ($slide.SlideShowTransition.AdvanceOnTime -eq $msoTrue -and $slide.SlideShowTransition.AdvanceTime -eq $expectedSeconds) "Run ${run}: slide $n advances after $expectedSeconds s"
        } else {
            Assert-True ($audioShapes.Count -eq 0) "Run ${run}: slide $n has no audio"
        }
    }
    $narrated.Close()
    $video = Get-Item (Join-Path $outFolder 'Test deck.narrated.mp4') -ErrorAction SilentlyContinue
    Assert-True ($null -ne $video -and $video.Length -gt 0) "Run ${run}: MP4 exported"
}
Assert-True ((Get-FileHash $deckPath).Hash -eq $originalHash) 'Original deck is unchanged'
Assert-True ($app.Presentations.Count -eq 0) 'The script closed every deck it opened'

$app.Quit()
[void] [System.Runtime.InteropServices.Marshal]::ReleaseComObject($app)

if ($failures -gt 0) { throw "$failures test(s) failed." }
Write-Host "All tests passed. Work folder: $WorkFolder"
