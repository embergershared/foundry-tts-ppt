# Plan: narrate a PowerPoint deck with Foundry text to speech

**Goal:** a Python command-line tool that turns text into speech with Microsoft Foundry, then
uses it to narrate a PowerPoint deck: one audio file per slide, made from the slide's speaker
notes, inserted in that slide.

Status: draft, to review before the GitHub issues are opened (one umbrella issue, one
sub-issue per phase, as the repository rules ask).

## Choices made for the whole plan

| Topic | Choice | Why |
|---|---|---|
| Azure resource | One **Foundry resource** (`Microsoft.CognitiveServices/accounts`, kind `AIServices`) with a Foundry project, public network access | One endpoint gives both TTS engines below. Private networking isn't needed. |
| TTS engines | **Azure Speech** (Speech SDK, SSML): HD voices (`en-US-Ava:DragonHDLatestNeural`) and MAI-Voice voices (`en-US-Harper:MAI-Voice-2.1`, preview) — no model deployment needed. **Azure OpenAI `gpt-4o-mini-tts`** (`/audio/speech`): one model deployment, the tone is steered with plain-English `instructions`. | Speech gives fine control (pauses, rate, pronunciation, styles, long text); `gpt-4o-mini-tts` is the quickest way to a natural presenter tone. The tool supports both, behind one interface, so they can be compared on the same text. |
| Region | `eastus2` or `swedencentral` (`gpt-4o-mini-tts` to confirm in phase 1) | Checked 2026-11-10: Dragon HD voices run in eastus, eastus2, westus2, westeurope, swedencentral, southeastasia, centralindia; MAI-Voice-2.1 is served from 14 regions, both of these included. `gpt-4o-mini-tts` must also be deployable there. |
| Infrastructure as code | Bicep, run with `azd provision` | The repository rules already use `azd` previews (`azd provision --preview`). |
| Authentication | Microsoft Entra ID (`DefaultAzureCredential`, i.e. `az login` locally), keys off (`disableLocalAuth: true`), role **Cognitive Services User** for the user | No secrets to store. |
| App | Python 3.13 CLI in `src/foundry_tts/`, tests in `tests/` (pytest, offline: the Azure clients are stubbed), ruff | Matches `.github/instructions/python.instructions.md`. |
| Config | `.env` (gitignored) with `.env.example` committed; read in one module (`config.py`) | Repository rules. |
| Audio format | MP3, 24 kHz, mono (`audio-24khz-160kbitrate-mono-mp3` / `mp3`) | PowerPoint plays MP3 everywhere; small files. For long decks, `audio-24khz-96kbitrate-mono-mp3` or `-48kbitrate-` cut the size (20 minutes of narration is about 24 MB at 160 kbps): compare by ear in phase 4. |

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
| Notes text | PowerPoint returns paragraphs separated by CR (tested) and line breaks inside a paragraph as a vertical tab, char 11 (handled, but not tested through PowerPoint). They become pauses and spaces in the SSML. Check what `python-pptx` returns for the same deck | 3 |
| Pauses | One `<break time="400ms"/>` between notes paragraphs (Dragon HD supports `<break>`) | 2, 3 |
| Rerun cache | The exact SSML sent is saved as `slide-NNN.ssml`; the audio is reused only when the new SSML is byte-identical. Hashing the final SSML catches note, voice, style, lexicon and markup changes in one value: use it as the manifest hash | 3, 5 |
| Insert audio | `Shapes.AddMediaObject2(file, LinkToFile=false, SaveWithDocument=true, left, top)`, placed just right of the slide (`left = SlideWidth + 20`), named so a rerun can find and replace it | 4 |
| Auto-play | `AnimationSettings.PlaySettings.PlayOnEntry = true`, `HideWhileNotPlaying = true` | 4 |
| Slide timing | `SlideShowTransition.AdvanceOnTime = true`, `AdvanceTime = ceil(MediaFormat.Length ms / 1000) + paddingSeconds` | 5 |
| Video | `Presentation.CreateVideo(path, UseTimingsAndNarrations=true, DefaultSlideDuration, VertResolution, FramesPerSecond, Quality)` runs in the background: poll `CreateVideoStatus` (3 = done, 4 = failed) with a timeout. A 3-slide test deck gave an 11 s MP4 with sound | 5 |
| Safety | The source deck is opened read-only without a window and saved under a new name; PowerPoint is quit only if the tool started it | 4 |

### What a real sample deck shows

A real deck, read on 2026-11-11 (15 slides, every slide with notes, none hidden). It is kept
**outside the repository**: its content is confidential, so nothing from it (file, notes, names,
audio made from it) is committed, put in an issue or PR, or quoted in the docs.

| Finding | What it means | Phase |
|---|---|---|
| The file is encrypted by a **Microsoft Purview sensitivity label** (an OLE compound file holding an `EncryptedPackage` and a DRM transform, not a ZIP) | `python-pptx` can't open it: it reads as a corrupt file. Desktop PowerPoint opens it read-only through COM, as the prototype does. Labeled decks have to be detected and either read through PowerPoint or refused with a clear message | 3, 4 |
| Notes come back from PowerPoint with paragraphs split by CR and **line breaks inside a paragraph as a vertical tab (char 11)**, plus empty paragraphs and double spaces | Confirms what the prototype handled but never tested. `split_paragraphs` already turns them into paragraphs and spaces | 3 |
| Notes are written for a presenter: `(Click)` cues, an emoji, `- ` bullets, stray `“` `"` quotes and a trailing ` .` | Read aloud as written today: the `(Click)` cues and the emoji would be spoken. Cleanups for phase 2 markup (below) | 2 |
| Acronyms spelled out (`IRS`, `W-2`), one said as a word, `&` inside acronyms (`Q&A`, `R&D`), number ranges with an en dash (`10–15`), an email address | Lexicon and `say-as` cases for phase 2 | 2 |
| About 18,500 characters of notes, roughly 3,000 words: **about 20 minutes of audio**. The longest slide's notes are 2,585 characters (about 2.6 minutes) | Under the 4,096-character `gpt-4o-mini-tts` limit and the 10-minute Speech limit: no splitting needed. At 160 kbps, 20 minutes of MP3 adds about 24 MB to the narrated deck | 3, 4 |
| No audio, animations, sections or slide timings yet (16:9, 960 × 540 pt) | A clean target for phases 4 and 5 | 4, 5 |

How it's used:

- **Local acceptance deck:** its path is set in a gitignored place (`.env` or a local config),
  and the tests that use it are opt-in and skipped in CI. It is the only check of a labeled deck.
- **CI:** a synthetic Contoso deck, built by a test, copies its quirks (CR and vertical tab
  breaks, empty paragraphs, `(Click)` cues, an emoji, `- ` bullets, stray quotes, acronyms, an
  en-dash range, an email address) and adds what it lacks: a hidden slide and a slide without
  notes. A deck that `python-pptx` writes can't be labeled, so CI covers the detection of a
  labeled file (from its header), not the reading of one.

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
`python -m foundry_tts --file samples/intro.txt --engine speech` and the same with
`--engine openai` each write an MP3 that plays; unit tests (SSML building, input reading,
config, engine selection with stubbed clients) pass; ruff passes;
`docs/getting-started.md` explains setup from zero.

### Phase 2: Voice tuning profiles

- `profiles.toml`: named profiles (engine, voice, rate, pitch, style, HD temperature,
  `instructions` for `gpt-4o-mini-tts`), chosen with `--profile narrator`.
- Pronunciation: a lexicon file (acronyms and product names, e.g. "AKS" → "A K S",
  "Azure" spelled as said) applied with SSML `<sub alias>` / `<phoneme>`, or a custom lexicon
  URL for Speech.
- Light markup that a presenter can type in plain notes and the tool turns into SSML:
  `[pause 1s]`, `*stress*`, and lines starting with `//` skipped (comments to self).
- Notes cleanups for what presenters already type (see the sample deck above): `(Click)` cues
  become a pause instead of being spoken, emoji are dropped, a leading `- ` or `•` is removed,
  stray quotes are dropped, an en-dash range (`10–15`) is read as "10 to 15". Each cleanup is
  logged, so a surprise can be traced.
- Lexicon cases to cover: an acronym spelled out (`IRS`), one said as a word, `&` inside an
  acronym (`Q&A` → "Q and A"), an email address.
- `--compare`: same text, several profiles → one file each, to pick by ear.

**Done when** profiles, lexicon and markup are covered by tests, and `docs/tts-tuning.md`
shows how to use them.

### Phase 3: Read a deck

- `foundry-tts deck synth deck.pptx`: reads each slide's speaker notes with `python-pptx`,
  applies the phase 2 markup and profile, and writes `output/<deck>/slide-01.mp3`, …
- **Sensitivity-labeled decks** (an encrypted OLE file instead of a ZIP) are detected from
  the file header before `python-pptx` opens them. **Decision to make at the start of this
  phase** (logged in `docs/decisions/`): read them through PowerPoint COM on Windows (the
  prototype's way, recommended since real decks may be labeled), or refuse them with a clear
  message that names the label as the reason. Either way, no "corrupt file" error.
- Slides without notes are skipped and listed; hidden slides are skipped unless
  `--include-hidden`.
- A `manifest.json` next to the audio: slide number, notes hash, voice, duration, file.
- Long notes: Speech handles up to 10 minutes per request; past that, the notes are split on
  paragraph boundaries and the parts joined. HD voices are real-time only (no batch synthesis
  API), so splitting is the only way for them.
- The manifest hash is taken over the final SSML (or the `gpt-4o-mini-tts` request), not the raw
  notes, so a voice, profile or lexicon change also counts as a change (as in the prototype).

**Done when** a sample deck (made by a test, no real content) gives one audio file per slide
with notes, and the manifest is right. That deck has the quirks listed in
[What a real sample deck shows](#what-a-real-sample-deck-shows), a hidden slide and a slide
without notes. A labeled file is detected in a test, and the local acceptance deck has been run
by hand.

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
  - **Labeled decks weigh on this choice:** option A can neither read nor write an encrypted
    deck, so with A, a labeled deck needs B anyway (or is refused). Check that a narrated copy
    saved by PowerPoint keeps the source deck's label.
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
| Rate and pitch | Speech (not HD) | `<prosody rate="-5%" pitch="+0%">`. **No HD voice supports `<prosody>`** (Dragon HD or Omni): use a MAI-Voice or standard voice when speed matters | Slightly slower than default (−5 to −10%) for slides |
| Pauses | Speech | `<break time="600ms"/>` (Dragon HD yes, Omni no); `<mstts:silence>` (no HD voice) | 300–500 ms `<break>` between paragraphs (the prototype uses 400 ms) |
| HD temperature | Speech (HD) | `parameters="temperature=0.6"`: lower is steadier from slide to slide (Dragon HD default 1.0) | 0.5–0.7 for a consistent voice across a deck |
| Pronunciation | Speech | `<sub alias="…">`, `<phoneme>`, `<say-as interpret-as="characters">`, custom lexicon. Dragon HD: lexicon alias entries only, no `<phoneme>` on Omni; `parameters="enhancePronunciation=true"` helps with acronyms and product names | Acronyms and product names |
| Language | Speech | `<lang xml:lang="fr-FR">` in a multilingual voice | Decks that mix languages |
| Instructions | `gpt-4o-mini-tts` | Plain-English direction of tone, pace and emotion | "Calm, confident conference presenter; clear diction; brief pause after each sentence." |
| Voice | `gpt-4o-mini-tts` | Alloy, Ash, Ballad, Coral, Echo, Sage, Shimmer, Verse, Marin, Cedar | Compare Marin, Cedar and Coral |
| Speed | `gpt-4o-mini-tts` | `speed` 0.25–4.0 | 0.95 |
| Output format | both | Sample rate and bitrate | 24 kHz mono MP3; 48 kHz only for video |
| Text hygiene | both | Notes written for reading aloud: no bullet fragments, spelled-out symbols ("→", "&", "%") | Phase 2 markup cleans the common ones |

SSML support differs by voice family
([HD voices: supported SSML](https://learn.microsoft.com/azure/ai-services/speech-service/high-definition-voices#supported-and-unsupported-ssml-elements-for-azure-speech-hd-voices)).
A profile that sets something its voice doesn't support (rate or pitch on an HD voice, for
example) is refused with a clear error when it's loaded, rather than sent and silently ignored.

## Open questions

- Which language(s) will the decks use? (Changes the voices to try first.)
- Is desktop PowerPoint on Windows always available where the tool runs? (Phase 3 and 4
  decisions.) Real decks may carry a sensitivity label, which only PowerPoint can open.
- Does a narrated copy saved by PowerPoint keep the source deck's sensitivity label, and do the
  label's rights let the user save a copy at all? (Phase 4; check on the local acceptance deck.)
- Once the Python tool reaches phase 5, is the PowerShell prototype kept (Windows users without
  Python) or removed?
- Subscription and region to use for phase 1.

## Sources

Checked on Microsoft Learn on 2026-11-10:
[Speech synthesis how-to](https://learn.microsoft.com/azure/ai-services/speech-service/how-to-speech-synthesis),
[HD voices](https://learn.microsoft.com/azure/ai-services/speech-service/high-definition-voices)
(and its supported SSML table),
[MAI-Voice in Azure Speech](https://learn.microsoft.com/azure/ai-services/speech-service/mai-voices),
[Foundry Models sold by Azure, audio models](https://learn.microsoft.com/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure#audio-models),
[Choose a speech technology](https://learn.microsoft.com/azure/architecture/data-guide/ai-services/speech-recognition-generation).
