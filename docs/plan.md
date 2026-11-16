# Plan: narrate a PowerPoint deck with Foundry text to speech

**Goal:** a Python command-line tool that turns text into speech with Microsoft Foundry, then
uses it to narrate a PowerPoint deck: one audio file per slide, made from the slide's speaker
notes, inserted in that slide.

Status: tracked in umbrella issue #8, one sub-issue per phase (#9 to #13). Phase 1 (#9) is
built: see [getting-started.md](getting-started.md).

## Choices made for the whole plan

| Topic | Choice | Why |
|---|---|---|
| Azure resource | One **Foundry resource** (`Microsoft.CognitiveServices/accounts`, kind `AIServices`) with a Foundry project, public network access | One endpoint gives both TTS engines below. Private networking isn't needed. |
| TTS engines | **Azure Speech** (REST API, SSML): HD voices (`en-US-Ava:DragonHDLatestNeural`) and MAI-Voice voices (`en-US-Harper:MAI-Voice-2.1`, preview) — no model deployment needed. **Azure OpenAI `gpt-4o-mini-tts`** (`/audio/speech`): one model deployment, the tone is steered with plain-English `instructions`. | Speech gives fine control (pauses, rate, pronunciation, styles, long text); `gpt-4o-mini-tts` is the quickest way to a natural presenter tone. The tool supports both, behind one interface, so they can be compared on the same text. |
| Region | **`eastus2`** | Checked 2026-11-10: Dragon HD voices run in eastus, eastus2, westus2, westeurope, swedencentral, southeastasia, centralindia; MAI-Voice-2.1 is served from 14 regions, both of these included. `gpt-4o-mini-tts` 2025-12-15 (GA, GlobalStandard) is offered in eastus2 but **not** in swedencentral (`az cognitiveservices model list`). |
| Infrastructure as code | Bicep, run with `azd provision` | The repository rules already use `azd` previews (`azd provision --preview`). |
| Authentication | Microsoft Entra ID (`DefaultAzureCredential`, i.e. `az login` locally), keys off (`disableLocalAuth: true`), role **Cognitive Services User** for the user | No secrets to store. |
| Azure calls (phase 1 decision) | **REST with `httpx` for both engines**, not the Speech SDK or the `openai` package. Speech: `https://<region>.tts.speech.microsoft.com/cognitiveservices/v1`, `Authorization: Bearer aad#<resource ID>#<Entra token>` (the format the Speech docs give for Entra tokens, as the prototype does). `gpt-4o-mini-tts`: `https://<resource>.openai.azure.com/openai/v1/audio/speech`, JSON body, plain Entra bearer token | One small HTTP dependency instead of a native SDK and a large client; the same error handling for both; offline tests with `httpx.MockTransport`. |
| App | Python 3.13 CLI in `src/foundry_tts/`, tests in `tests/` (pytest, offline: the Azure clients are stubbed), ruff | Matches `.github/instructions/python.instructions.md`. |
| Config | `.env` (gitignored) with `.env.example` committed; read in one module (`config.py`) | Repository rules. |
| Audio format | MP3, 24 kHz, mono (`audio-24khz-160kbitrate-mono-mp3` / `mp3`) | PowerPoint plays MP3 everywhere; small files. |

## Phases

| # | Phase | Delivers |
|---|---|---|
| 0 | Initialize the repository | Template placeholders filled, .NET stack removed (PR #2) |
| 1 | Text to speech tool | Foundry resource + model, CLI: text or file in → audio file out, tuning guide |
| 2 | Voice tuning profiles | Named, reusable voice settings; pronunciation fixes; markup for pauses |
| 3 | Read a deck | Speaker notes of each slide → one audio file per slide |
| 4 | Narrate a deck | Audio inserted in each slide, plays when the slide shows |
| 5 | Hands-free deck | Slides advance when their narration ends; re-runs only redo changed slides; optional video export |

### What the PowerShell prototype already shows

A PowerShell prototype ([docs/powershell-prototype.md](powershell-prototype.md),
`src/powershell-prototype/`) does phases 3 to 5 with option B (PowerPoint COM) and the Speech
REST API. Its tests pass on Windows with desktop PowerPoint, using generated tones instead of
Azure; **the Azure call itself hasn't been tested yet**. Use it as the reference behavior:

| Topic | What the prototype does, tested | Phase |
|---|---|---|
| Notes text | PowerPoint returns paragraphs separated by CR (tested) and line breaks inside a paragraph as a vertical tab, char 11. They become pauses and spaces in the SSML. `python-pptx` returns the same text with LF between paragraphs: checked through PowerPoint in #11 | 3 |
| Pauses | One `<break time="400ms"/>` between notes paragraphs (Dragon HD supports `<break>`) | 2, 3 |
| Rerun cache | The exact SSML sent is saved as `slide-NNN.ssml`; the audio is reused only when the new SSML is byte-identical. Hashing the final SSML catches note, voice, style, lexicon and markup changes in one value: use it as the manifest hash | 3, 5 |
| Insert audio | `Shapes.AddMediaObject2(file, LinkToFile=false, SaveWithDocument=true, left, top)`, placed just right of the slide (`left = SlideWidth + 20`), named so a rerun can find and replace it | 4 |
| Auto-play | `AnimationSettings.PlaySettings.PlayOnEntry = true`, `HideWhileNotPlaying = true` | 4 |
| Slide timing | `SlideShowTransition.AdvanceOnTime = true`, `AdvanceTime = ceil(MediaFormat.Length ms / 1000) + paddingSeconds` | 5 |
| Video | `Presentation.CreateVideo(path, UseTimingsAndNarrations=true, DefaultSlideDuration, VertResolution, FramesPerSecond, Quality)` runs in the background: poll `CreateVideoStatus` (3 = done, 4 = failed) with a timeout. A 3-slide test deck gave an 11 s MP4 with sound | 5 |
| Safety | The source deck is opened read-only without a window and saved under a new name; PowerPoint is quit only if the tool started it | 4 |

### Phase 0: Initialize the repository

The repository is still the raw `embergershared/repo-template` (`__PROJECT_NAME__` in the
README and the rules).

- Run `./scripts/Initialize-Repo.ps1 -Description '<one line>' -Stacks python`. It removes the
  .NET files, fills the placeholders, sets the GitHub repository up, and opens its own issue and
  PR.
- Fill the *This project* section of `.github/copilot-instructions.md`.

**Done when** that PR is merged and `main` has no placeholders left.

### Phase 1: Text to speech tool

1. **Foundry resource and model** (`infra/`, Bicep + `azure.yaml`):
   - Foundry resource (kind `AIServices`, SKU `S0`, custom subdomain, keys off) and a project.
   - Model deployment `gpt-4o-mini-tts` (GlobalStandard, small capacity).
   - Role assignment *Cognitive Services User* for the signed-in user.
   - Outputs only names and the endpoint (no keys).
   - `azd provision --preview` first; the real `azd provision` only after your go-ahead.
2. **Python CLI** (`src/foundry_tts/`):
   - Text in three ways: `--text "…"`, `--file notes.txt` (UTF-8, BOM stripped), or standard
     input.
   - `--engine speech|openai`, `--voice`, `--out <path>` (default: a timestamped file in
     `output/`, gitignored).
   - Engine `speech`: Speech SDK, SSML built by the tool (plain text is escaped), Entra ID token.
   - Engine `openai`: `openai` package (`AzureOpenAI` client, Entra ID token provider),
     `audio.speech.create(model=<deployment>, voice=…, input=…, instructions=…)`.
   - A `--ssml file.xml` option for hand-written SSML (engine `speech` only).
   - Errors fail loudly: the service's cancellation reason or HTTP error is shown, no file is
     written.
   - Structured logging (`logging`), no `print` for diagnostics.
3. **Download the audio**: both engines return the audio bytes; the tool writes the file and
   logs its path, size and duration.
4. **Tuning guide** `docs/tts-tuning.md`: what to change to make the voice sound better (see
   [Tuning ideas](#tuning-ideas) below), each with a ready-to-run command.

**Done when:** `az login`, then
`foundry-tts --file notes.txt --engine speech` and the same with
`--engine openai` each write an MP3 that plays; unit tests (SSML building, input reading,
config, engine selection with stubbed clients) pass; ruff passes;
`docs/getting-started.md` explains setup from zero.

### Phase 2: Voice tuning profiles

Built in #10 (see [tts-tuning.md](tts-tuning.md)). What changed from the first draft:

- Profiles live in `foundry-tts.toml` (`[profiles.<name>]`, default in `[defaults] profile`),
  so `config.py` stays the only reader of settings. `--engine` is gone: the engine is a profile
  setting.
- Pronunciation: a `[lexicon]` table in the same file, plus `--lexicon <file>` for a deck's own
  words; speech voices get `<sub alias>`, the openai engine the replacement text. `<phoneme>`
  stays for hand-written SSML.
- Markup: `//` comment lines and `[pause …]`. `*stress*` was dropped: `<emphasis>` works on
  three standard voices only.
- Comparing: `--profile` repeated (one file per profile), instead of a separate `--compare`.
- What each voice family honors was **measured** against the service, because the docs
  disagree with it: `<prosody>` works on Dragon HD and Omni, `<break>` works on Omni, and
  MAI-Voice ignores `<break>`. So only temperature on non-HD voices is refused; pauses for MAI
  voices are left out with a warning.

**Done when** profiles, lexicon and markup are covered by tests, and `docs/tts-tuning.md`
shows how to use them.

### Phase 3: Read a deck

Built in #11 (see [getting-started.md](getting-started.md#5-narrate-a-decks-speaker-notes)):

- `foundry-tts deck synth deck.pptx` writes `output/<deck>/slide-01.mp3`, … and
  `manifest.json`, with one profile (`--profile`, and the same overrides as for text).
- **Labeled decks** ([decision 0001](decisions/0001-read-labeled-decks-through-powerpoint.md)):
  an OLE file instead of a ZIP (a sensitivity label, a password, or an old .ppt) is detected from
  its first bytes and read through desktop PowerPoint (COM, `pywin32`), read-only and without a
  window; other decks with `python-pptx`. `--reader` forces one or the other.
- Notes cleanups, planned for phase 2 and built here: `(Click)` cues become a pause
  (`[deck] cue_pause_ms`), emoji and double quotes are dropped, a bullet becomes its own
  paragraph, an en-dash range is read "10 to 15", a space before punctuation is removed. Each
  one is counted in the log and the manifest.
- Slides without notes (or only `//` comments) and hidden slides (unless `--include-hidden`) are
  skipped and listed in the manifest with their reason.
- Long text, for decks and plain text alike: more than `[speech] max_chars_per_request` (6,000
  characters, about 6 minutes; Azure Speech cuts audio at 10 minutes per request) or the 4,096
  characters of `gpt-4o-mini-tts` is split between paragraphs, else sentences, and the MP3 parts
  are joined (a later part's ID3 tag is dropped). Checked against Azure for both engines.
- The manifest hash is the sha256 of the exact request bodies sent (the SSML, or the
  `gpt-4o-mini-tts` JSON), so a notes, profile, lexicon or settings change changes it. Phase 5
  uses it to skip unchanged slides.
- Everything is read and checked before the first Azure call; the manifest is written last, so it
  always describes a complete run.

**Done when** a sample deck (made by a test, no real content) gives one audio file per slide
with notes, and the manifest is right: `tests/decks.py` builds a Contoso deck with the quirks of a
real one, a hidden slide, a slide without notes and one with only a comment. A labeled file is
detected in a test, and a real labeled deck was read through PowerPoint by hand (15 slides, every
cleanup used).

### Phase 4: Narrate a deck

- `foundry-tts deck narrate deck.pptx`: writes `deck.narrated.pptx` (the original is never
  changed) with the slide's audio inserted, the speaker icon small and off the slide's
  visible area or hidden during the show, set to play automatically when the slide shows.
- **Decision to make at the start of this phase** (logged in `docs/decisions/`):
  - **A. Open XML with `python-pptx`** (recommended): no Office needed, runs in CI and on any
    OS. `python-pptx` has no audio API, so the tool adds the media part, the audio shape and
    the slide's `<p:timing>` (auto-play) itself. Needs checking in PowerPoint by hand.
  - **B. PowerPoint automation (COM, `pywin32`)**: `Shapes.AddMediaObject2`, play settings
    set through PowerPoint's own object model; most faithful, but Windows + desktop
    PowerPoint only, and can't be tested in CI. **Already proven** by the PowerShell
    prototype (see the table above).
  - Either way, a deck narrated by the prototype is the reference for option A: unzip it to
    see the exact media parts, relationships and `<p:timing>` that PowerPoint itself writes,
    and compare the tool's output with it in tests.
- Re-running replaces the audio the tool inserted before (shapes it inserted are tagged), and
  leaves other media alone.

**Done when** the narrated deck opens in PowerPoint without a repair prompt, each slide plays
its narration on its own in Slide Show, and tests check the package structure.

### Phase 5: Hands-free deck

- Slide advance after the narration ends (+ a configurable gap), from the durations in the
  manifest, so the deck can run as a kiosk or self-running presentation.
- Incremental runs: only slides whose notes, profile or lexicon changed are re-synthesized
  (hash in the manifest), to save time and cost.
- Optional: export to MP4 (PowerPoint `CreateVideo` through COM, Windows only; asynchronous, see
  the prototype table above). Slides without notes need a default duration in the video.
- Optional: `azd down` instructions and a cost note in the docs.

**Done when** a narrated deck runs start to end in Slide Show without a click, and a re-run
with one changed note re-synthesizes only that slide.

## Tuning ideas

These go into `docs/tts-tuning.md` in phase 1, then become profile settings in phase 2.

| Lever | Engine | What it does | Starting point for slide narration |
|---|---|---|---|
| Voice and model | Speech | HD (`…:DragonHDLatestNeural`) is natural and stable; MAI-Voice-2.1 (preview) is the most expressive, made for long-form narration | Try `en-US-Ava:DragonHDLatestNeural` and `en-US-Harper:MAI-Voice-2.1` |
| Speaking style | Speech | `<mstts:express-as style="…">`; MAI-Voice Harper, Grant and Sage (en-US) offer `narrator`, `educational`, `audiobook`. Dragon HD: its SSML support table says no `express-as`, while an example on the same page uses one: test before relying on it. Dragon HD Omni supports styles | `narrator` or `educational` (MAI-Voice) |
| Rate and pitch | Speech | `<prosody rate="-5%" pitch="+0%">`. The docs say HD voices don't support it, but `rate` measurably works on Dragon HD and Omni (2026-11-11) | Slightly slower than default (−5 to −10%) for slides |
| Pauses | Speech | `<break time="600ms"/>` (Dragon HD yes, Omni no); `<mstts:silence>` (no HD voice) | 300–500 ms `<break>` between paragraphs (the prototype uses 400 ms) |
| HD temperature | Speech (HD) | `parameters="temperature=0.6"`: lower is steadier from slide to slide (Dragon HD default 1.0) | 0.5–0.7 for a consistent voice across a deck |
| Pronunciation | Speech | `<sub alias="…">`, `<phoneme>`, `<say-as interpret-as="characters">`, custom lexicon. Dragon HD: lexicon alias entries only, no `<phoneme>` on Omni; `parameters="enhancePronunciation=true"` helps with acronyms and product names | Acronyms and product names |
| Language | Speech | `<lang xml:lang="fr-FR">` in a multilingual voice | Decks that mix languages |
| Instructions | `gpt-4o-mini-tts` | Plain-English direction of tone, pace and emotion | "Calm, confident conference presenter; clear diction; brief pause after each sentence." |
| Voice | `gpt-4o-mini-tts` | Alloy, Ash, Ballad, Coral, Echo, Sage, Shimmer, Verse, Marin, Cedar | Compare Marin, Cedar and Coral |
| Pace | `gpt-4o-mini-tts` | Ask for it in `instructions` (the tool sends no `speed` value) | "Slightly slower than normal" |
| Output format | both | Sample rate and bitrate | 24 kHz mono MP3; 48 kHz only for video |
| Text hygiene | both | Notes written for reading aloud: no bullet fragments, spelled-out symbols ("→", "&", "%") | Phase 2 markup cleans the common ones |

SSML support differs by voice family
([HD voices: supported SSML](https://learn.microsoft.com/azure/ai-services/speech-service/high-definition-voices#supported-and-unsupported-ssml-elements-for-azure-speech-hd-voices)).
A profile that sets something its voice doesn't support (temperature on a MAI-Voice voice, for
example) is refused with a clear error when it's loaded, rather than sent and silently ignored.
Measured on 2026-11-11, `<prosody>` works on HD voices despite that table: see
[tts-tuning.md](tts-tuning.md#5-what-each-voice-family-honors).

## Open questions

- Which language(s) will the decks use? (Changes the voices to try first.)
- Is desktop PowerPoint on Windows always available where the tool runs? (Phase 4 decision.)
- Once the Python tool reaches phase 5, is the PowerShell prototype kept (Windows users without
  Python) or removed?

## Sources

Checked on Microsoft Learn on 2026-11-10:
[Speech synthesis how-to](https://learn.microsoft.com/azure/ai-services/speech-service/how-to-speech-synthesis),
[HD voices](https://learn.microsoft.com/azure/ai-services/speech-service/high-definition-voices)
(and its supported SSML table),
[MAI-Voice in Azure Speech](https://learn.microsoft.com/azure/ai-services/speech-service/mai-voices),
[Foundry Models sold by Azure, audio models](https://learn.microsoft.com/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure#audio-models),
[Choose a speech technology](https://learn.microsoft.com/azure/architecture/data-guide/ai-services/speech-recognition-generation).
