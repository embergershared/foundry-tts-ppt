#Requires -Version 7.0
# Functions for Convert-NotesToAudio.ps1: read PowerPoint speaker notes, synthesize them with
# Azure Speech text to speech, and add the audio to the slides.

Set-StrictMode -Version Latest

# Office API constants (MsoTriState, PpPlaceholderType, PpMediaTaskStatus).
$script:msoTrue = -1
$script:msoFalse = 0
$script:ppPlaceholderBody = 2
$script:ppMediaTaskStatusDone = 3
$script:ppMediaTaskStatusFailed = 4

# Microsoft Entra resource for Azure AI services tokens.
$script:cognitiveServicesResource = 'https://cognitiveservices.azure.com'

# Cached Entra token for this run.
$script:speechToken = $null
$script:speechTokenTime = [datetime]::MinValue

function Write-NotesLog {
    <# Writes one structured (JSON) log line. #>
    param(
        [ValidateSet('DEBUG', 'INFO', 'WARNING', 'ERROR')]
        [string] $Level = 'INFO',
        [Parameter(Mandatory)] [string] $Message,
        [hashtable] $Data = @{}
    )
    $entry = [ordered]@{
        time    = (Get-Date).ToUniversalTime().ToString('o')
        level   = $Level
        message = $Message
    }
    foreach ($key in $Data.Keys) { $entry[$key] = $Data[$key] }
    $line = $entry | ConvertTo-Json -Compress
    switch ($Level) {
        'DEBUG' { Write-Debug $line }
        'WARNING' { Write-Warning $line }
        'ERROR' { [Console]::Error.WriteLine($line) }
        default { Write-Information $line -InformationAction Continue }
    }
}

function Get-NotesToAudioSettings {
    <#
    Reads the JSON config file and the environment variables. This is the only place that reads
    either. Fails when a setting needed for this run is missing.
    #>
    param(
        [Parameter(Mandatory)] [string] $Path,
        [bool] $NeedsSpeech = $true
    )
    if (-not (Test-Path -LiteralPath $Path)) { throw "Config file not found: $Path" }
    $settings = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json

    $settings | Add-Member -NotePropertyName env -NotePropertyValue ([pscustomobject]@{
            SpeechKey = $env:AZURE_SPEECH_KEY
        })

    if ($NeedsSpeech) {
        $speech = $settings.speech
        if ($speech.auth -notin 'Entra', 'Key') {
            throw "speech.auth must be 'Entra' or 'Key' (found '$($speech.auth)')."
        }
        if ($speech.auth -eq 'Entra' -and [string]::IsNullOrWhiteSpace($speech.resourceId)) {
            throw 'speech.auth is Entra, so speech.resourceId must be the Azure resource ID of the Speech or Foundry resource.'
        }
        if ($speech.auth -eq 'Key' -and [string]::IsNullOrWhiteSpace($settings.env.SpeechKey)) {
            throw 'speech.auth is Key, but the AZURE_SPEECH_KEY environment variable is not set.'
        }
        if ([string]::IsNullOrWhiteSpace($speech.endpoint) -and [string]::IsNullOrWhiteSpace($speech.region)) {
            throw 'Set speech.region (for example eastus) or speech.endpoint in the config file.'
        }
        if ([string]::IsNullOrWhiteSpace($speech.voice)) { throw 'Set speech.voice in the config file.' }
    }
    return $settings
}

function Get-AudioExtension {
    <# Maps an Azure Speech output format to a file extension that PowerPoint can play. #>
    param([Parameter(Mandatory)] [string] $OutputFormat)
    if ($OutputFormat -match 'mp3') { return '.mp3' }
    if ($OutputFormat -like 'riff-*') { return '.wav' }
    throw "Output format '$OutputFormat' is not supported here. Use an MP3 format (audio-*-mp3) or a RIFF/WAV format (riff-*)."
}

function Get-SlideNotes {
    <# Returns the speaker notes text of a slide, or an empty string. #>
    param([Parameter(Mandatory)] $Slide)
    foreach ($shape in $Slide.NotesPage.Shapes.Placeholders) {
        if ($shape.PlaceholderFormat.Type -eq $script:ppPlaceholderBody -and $shape.HasTextFrame -eq $script:msoTrue) {
            return [string] $shape.TextFrame.TextRange.Text
        }
    }
    return ''
}

function ConvertTo-NotesSsml {
    <#
    Builds the SSML for one slide. Each notes paragraph is escaped for XML; paragraphs are
    separated by a short pause. A rate is applied only when one is configured.
    #>
    param(
        [Parameter(Mandatory)] [AllowEmptyString()] [string] $Text,
        [Parameter(Mandatory)] $Speech
    )
    # PowerPoint separates paragraphs with CR and uses vertical tab (char 11) for line breaks.
    $paragraphs = @(
        $Text -split "[`r`n]+" |
            ForEach-Object { ($_ -replace [char]11, ' ').Trim() } |
            Where-Object { $_ }
    )
    if ($paragraphs.Count -eq 0) { throw 'The notes text is empty; there is nothing to synthesize.' }

    $pause = " <break time=`"$($Speech.paragraphBreakMs)ms`"/> "
    $body = ($paragraphs | ForEach-Object { [System.Security.SecurityElement]::Escape($_) }) -join $pause
    if (-not [string]::IsNullOrWhiteSpace($Speech.rate)) {
        $body = "<prosody rate=`"$([System.Security.SecurityElement]::Escape($Speech.rate))`">$body</prosody>"
    }
    if (-not [string]::IsNullOrWhiteSpace($Speech.style)) {
        $body = "<mstts:express-as style=`"$([System.Security.SecurityElement]::Escape($Speech.style))`">$body</mstts:express-as>"
    }
    $language = [System.Security.SecurityElement]::Escape($Speech.language)
    $voice = [System.Security.SecurityElement]::Escape($Speech.voice)
    return "<speak version=`"1.0`" xmlns=`"http://www.w3.org/2001/10/synthesis`" xmlns:mstts=`"http://www.w3.org/2001/mstts`" xml:lang=`"$language`"><voice name=`"$voice`">$body</voice></speak>"
}

function Get-SpeechAuthHeader {
    <# Returns the auth header: the resource key, or a Microsoft Entra token from the Azure CLI. #>
    param([Parameter(Mandatory)] $Settings)
    if ($Settings.speech.auth -eq 'Key') {
        return @{ 'Ocp-Apim-Subscription-Key' = $Settings.env.SpeechKey }
    }
    $age = (Get-Date) - $script:speechTokenTime
    if (-not $script:speechToken -or $age.TotalMinutes -ge $Settings.speech.tokenRefreshMinutes) {
        $entraToken = az account get-access-token --resource $script:cognitiveServicesResource --query accessToken --output tsv
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($entraToken)) {
            throw 'Could not get a Microsoft Entra token from the Azure CLI. Run az login, then try again.'
        }
        # Speech accepts Entra tokens in the form aad#<resource ID>#<token>.
        $script:speechToken = "aad#$($Settings.speech.resourceId)#$entraToken"
        $script:speechTokenTime = Get-Date
        Write-NotesLog -Message 'Got a Microsoft Entra token from the Azure CLI.'
    }
    return @{ Authorization = "Bearer $script:speechToken" }
}

function Invoke-SpeechSynthesis {
    <# Calls the Azure Speech text to speech REST API and saves the audio to OutFile. #>
    param(
        [Parameter(Mandatory)] [string] $Ssml,
        [Parameter(Mandatory)] [string] $OutFile,
        [Parameter(Mandatory)] $Settings
    )
    $speech = $Settings.speech
    $uri = if ([string]::IsNullOrWhiteSpace($speech.endpoint)) {
        "https://$($speech.region).tts.speech.microsoft.com/cognitiveservices/v1"
    } else { $speech.endpoint }

    $headers = Get-SpeechAuthHeader -Settings $Settings
    $headers['X-Microsoft-OutputFormat'] = $speech.outputFormat
    $body = [System.Text.Encoding]::UTF8.GetBytes($Ssml)
    try {
        Invoke-WebRequest -Method Post -Uri $uri -Headers $headers -UserAgent 'notes-to-audio' `
            -ContentType 'application/ssml+xml; charset=utf-8' -Body $body -OutFile $OutFile | Out-Null
    } catch {
        Remove-Item -LiteralPath $OutFile -ErrorAction SilentlyContinue
        $status = if ($_.Exception.PSObject.Properties['Response'] -and $_.Exception.Response) {
            [int] $_.Exception.Response.StatusCode
        } else { 'none' }
        throw "Azure Speech synthesis failed (HTTP $status) at $uri. $($_.ErrorDetails.Message) $($_.Exception.Message)"
    }
    if ((Get-Item -LiteralPath $OutFile).Length -eq 0) {
        throw "Azure Speech returned an empty audio file for $OutFile."
    }
}

function Find-SlideAudio {
    <# Finds an existing audio file for a slide (stem + .mp3 or .wav). #>
    param([Parameter(Mandatory)] [string] $Stem)
    foreach ($extension in '.mp3', '.wav') {
        if (Test-Path -LiteralPath "$Stem$extension") { return "$Stem$extension" }
    }
    return $null
}

function Add-SlideNarration {
    <#
    Adds the audio to a slide: removes narration added by an earlier run, embeds the audio off
    the visible slide area, sets it to play automatically, and times the slide to the audio
    length plus padding. Returns the slide duration in seconds.
    #>
    param(
        [Parameter(Mandatory)] $Slide,
        [Parameter(Mandatory)] [string] $AudioPath,
        [Parameter(Mandatory)] $SlideSettings,
        [Parameter(Mandatory)] [single] $SlideWidth
    )
    for ($i = $Slide.Shapes.Count; $i -ge 1; $i--) {
        $existing = $Slide.Shapes.Item($i)
        if ($existing.Name -eq $SlideSettings.audioShapeName) { $existing.Delete() }
    }

    $left = $SlideWidth + $SlideSettings.offSlideMarginPoints
    $shape = $Slide.Shapes.AddMediaObject2($AudioPath, $script:msoFalse, $script:msoTrue, $left, 0)
    $shape.Name = $SlideSettings.audioShapeName

    $play = $shape.AnimationSettings.PlaySettings
    $play.PlayOnEntry = $script:msoTrue
    $play.HideWhileNotPlaying = $script:msoTrue

    $lengthMs = $shape.MediaFormat.Length
    if ($lengthMs -le 0) { throw "PowerPoint reports a zero length for the audio $AudioPath." }
    $seconds = [math]::Ceiling($lengthMs / 1000.0) + $SlideSettings.paddingSeconds

    $transition = $Slide.SlideShowTransition
    $transition.AdvanceOnTime = $script:msoTrue
    $transition.AdvanceTime = $seconds
    return $seconds
}

function Export-PresentationVideo {
    <# Exports the presentation to MP4 with its timings and narration and waits for the export. #>
    param(
        [Parameter(Mandatory)] $Presentation,
        [Parameter(Mandatory)] [string] $Path,
        [Parameter(Mandatory)] $VideoSettings
    )
    if (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $Path }
    $Presentation.CreateVideo($Path, $true, $VideoSettings.defaultSlideSeconds, $VideoSettings.verticalResolution,
        $VideoSettings.framesPerSecond, $VideoSettings.quality)

    $deadline = (Get-Date).AddMinutes($VideoSettings.timeoutMinutes)
    while ($true) {
        $status = $Presentation.CreateVideoStatus
        if ($status -eq $script:ppMediaTaskStatusDone) { break }
        if ($status -eq $script:ppMediaTaskStatusFailed) { throw "PowerPoint failed to export the video $Path." }
        if ((Get-Date) -gt $deadline) {
            throw "The video export did not finish within $($VideoSettings.timeoutMinutes) minutes."
        }
        Start-Sleep -Seconds $VideoSettings.pollSeconds
    }
}

Export-ModuleMember -Function Write-NotesLog, Get-NotesToAudioSettings, Get-AudioExtension, Get-SlideNotes,
    ConvertTo-NotesSsml, Invoke-SpeechSynthesis, Find-SlideAudio, Add-SlideNarration, Export-PresentationVideo
