# PowerShell prototype: narrate a deck through PowerPoint

A working prototype, written before the Python tool of [plan.md](plan.md). It covers phases 3 to 5
of the plan with **option B** (PowerPoint automation through COM). For each slide that has
speaker notes, it:

1. reads the speaker notes;
2. makes one audio file per slide with the **Azure Speech text to speech** REST API (Microsoft
   Foundry);
3. saves a **narrated copy** of the deck: each slide's audio is embedded, plays automatically, and
   the slide moves on when the audio ends;
4. exports the narrated copy to **MP4** (optional).

The original deck is never changed.

| File | What it is |
|---|---|
| [`src/powershell-prototype/Convert-NotesToAudio.ps1`](../src/powershell-prototype/Convert-NotesToAudio.ps1) | The script you run |
| [`src/powershell-prototype/NotesToAudio.psm1`](../src/powershell-prototype/NotesToAudio.psm1) | Its functions (notes, SSML, Azure call, PowerPoint steps) |
| [`src/powershell-prototype/notes-to-audio.config.json`](../src/powershell-prototype/notes-to-audio.config.json) | Settings: voice, Azure resource, timing, video |
| [`tests/powershell-prototype/Test-NotesToAudio.ps1`](../tests/powershell-prototype/Test-NotesToAudio.ps1) | Tests that don't need Azure |

## What has been verified

| Check | Status |
|---|---|
| Notes read; slides without notes skipped | Tested |
| Audio added once per slide, plays automatically, placed off the visible slide | Tested |
| Each slide advances after its audio length (rounded up) plus `paddingSeconds` | Tested |
| A rerun replaces the audio it added (no duplicates) | Tested |
| MP4 export with the narration | Tested: a 3-slide deck gives an 11 s video with a sound track |
| Original deck unchanged | Tested |
| **The call to Azure Speech** (Entra or key) | **Not tested yet.** The tests use generated tones instead |
| Running while PowerPoint is already open | Not tested; close PowerPoint first |

## What you need

- Windows with **PowerPoint** (desktop) and **PowerShell 7**.
- A **Microsoft Foundry** (or Speech) resource in a region that has the voice you pick.
- For Microsoft Entra sign-in (the default): the **Azure CLI**, signed in with `az login`, and the
  **Cognitive Services Speech User** (or **Cognitive Services User**) role on the resource. The
  resource needs a custom subdomain (Foundry resources have one).
- Or, for key sign-in: the resource key in the `AZURE_SPEECH_KEY` environment variable.

## Settings (`notes-to-audio.config.json`)

| Setting | Meaning |
|---|---|
| `speech.auth` | `Entra` (Azure CLI token, recommended) or `Key` (`AZURE_SPEECH_KEY` env var) |
| `speech.resourceId` | Azure resource ID of the Foundry/Speech resource (Entra only). Portal → resource → **Properties**. Keep the real value out of the repository |
| `speech.region` | Region of the resource, e.g. `eastus`. The script calls `https://<region>.tts.speech.microsoft.com/cognitiveservices/v1` |
| `speech.endpoint` | Optional: a full text to speech URL that replaces the region URL |
| `speech.voice` | Voice name, e.g. `en-US-Ava:DragonHDLatestNeural` (the default) |
| `speech.language` | SSML language, e.g. `en-US` |
| `speech.style` | Optional speaking style (the styles each voice supports differ). **Leave empty for Dragon HD voices**: they pick the tone from the text, and their SSML support table doesn't list `express-as` |
| `speech.rate` | Optional speed, e.g. `+10%`. **Leave empty for Dragon HD voices**: they don't support `<prosody>` |
| `speech.outputFormat` | An MP3 (`audio-…-mp3`) or WAV (`riff-…`) format |
| `speech.paragraphBreakMs` | Pause between notes paragraphs (`<break>`, supported by Dragon HD) |
| `speech.tokenRefreshMinutes` | How often the Entra token is renewed during a long run |
| `slides.paddingSeconds` | Extra time on each slide after its audio ends |
| `slides.audioShapeName` | Name of the inserted audio; a rerun replaces audio with this name |
| `slides.offSlideMarginPoints` | The audio is placed just right of the slide, so it never shows |
| `video.*` | MP4 export: on/off, height (1080), frames per second, quality, seconds for slides without notes, timeout |

To keep a real resource ID out of the repository, copy the config file outside the repository
and pass it with `-ConfigPath`.

### Which voice

| Use | Voice example | Status |
|---|---|---|
| Natural narration that picks its own emotion (default) | `en-US-Ava:DragonHDLatestNeural` | GA. HD voices run in eastus, eastus2, westus2, westeurope, swedencentral, southeastasia, centralindia |
| Most expressive model, set by style | `en-US-Harper:MAI-Voice-2.1` with style `narrator`, `educational` or `audiobook` | Public preview |
| Faster, cheaper, live use | `en-US-Harper:MAI-Voice-2.1-Flash` | Public preview |
| Full SSML control (speed, emphasis, styles) | `en-US-AvaMultilingualNeural` (standard, same Ava persona) | GA |

In the Foundry playground, **Voice: Ava** + **Model: Dragon HD Latest** is
`en-US-Ava:DragonHDLatestNeural`. Try voices first there:
[Text to speech](https://aka.ms/foundry-text-to-speech) → **Open in playground**.

## Run it

PowerShell (workstation), PowerPoint closed:

```powershell
Set-Location '<clone>\src\powershell-prototype'
az login
./Convert-NotesToAudio.ps1 -Presentation 'C:\Decks\Quarterly review.pptx' -ConfigPath 'C:\Decks\notes-to-audio.config.json'
```

Results go to `C:\Decks\Quarterly review-narration\`:

| Output | What it is |
|---|---|
| `slide-NNN.txt` | The notes text of each slide |
| `slide-NNN.mp3` | The audio of each slide |
| `slide-NNN.ssml` | The SSML sent to Azure; when it hasn't changed, the next run reuses the audio (no new cost) |
| `<deck>.narrated.pptx` | The deck with narration and slide timings |
| `<deck>.narrated.mp4` | The video (when `video.enabled` is true) |

Other options:

```powershell
./Convert-NotesToAudio.ps1 -Presentation '.\deck.pptx' -NotesOnly       # only extract the notes; no Azure, no deck
./Convert-NotesToAudio.ps1 -Presentation '.\deck.pptx' -SkipVideo       # narrated deck, no MP4
./Convert-NotesToAudio.ps1 -Presentation '.\deck.pptx' -SkipSynthesis   # reuse the audio files already in the output folder
```

Each step writes one JSON log line. The script stops with an error when a step fails (no audio,
Azure error, PowerPoint error); it doesn't skip slides silently.

## Limits and notes

- One Azure request per slide. A request can't produce more than 10 minutes of audio; split
  longer notes.
- Slides without notes get no audio and, in the video, show for `video.defaultSlideSeconds`.
- The audio plays automatically when its slide opens. On slides with click animations, check the
  order in **Animations → Animation Pane**.
- To fix how a word is said, use SSML (`<phoneme>`, `<sub>`) or a
  [custom lexicon](https://learn.microsoft.com/azure/ai-services/speech-service/speech-synthesis-markup-pronunciation)
  (Dragon HD voices accept alias entries only).
- The script quits PowerPoint at the end only if it started it.

## Tests

PowerShell (workstation), PowerPoint closed:

```powershell
Set-Location '<clone>'
./tests/powershell-prototype/Test-NotesToAudio.ps1
```

They check SSML building (escaping, pauses, style, rate), notes extraction, audio insertion, slide
timings, reruns (no duplicate audio) and the MP4 export, using generated WAV tones instead of
Azure. They need desktop PowerPoint, so CI doesn't run them.
