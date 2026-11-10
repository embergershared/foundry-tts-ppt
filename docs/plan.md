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
| Region | `eastus2` or `swedencentral` (to confirm in phase 1 against the current region tables) | Both list MAI-Voice and HD voices; `gpt-4o-mini-tts` must also be deployable there. |
| Infrastructure as code | Bicep, run with `azd provision` | The repository rules already use `azd` previews (`azd provision --preview`). |
| Authentication | Microsoft Entra ID (`DefaultAzureCredential`, i.e. `az login` locally), keys off (`disableLocalAuth: true`), role **Cognitive Services User** for the user | No secrets to store. |
| App | Python 3.13 CLI in `src/foundry_tts/`, tests in `tests/` (pytest, offline: the Azure clients are stubbed), ruff | Matches `.github/instructions/python.instructions.md`. |
| Config | `.env` (gitignored) with `.env.example` committed; read in one module (`config.py`) | Repository rules. |
| Audio format | MP3, 24 kHz, mono (`audio-24khz-160kbitrate-mono-mp3` / `mp3`) | PowerPoint plays MP3 everywhere; small files. |

## Phases

| # | Phase | Delivers |
|---|---|---|
| 0 | Initialize the repository | Template placeholders filled, .NET stack removed |
| 1 | Text to speech tool | Foundry resource + model, CLI: text or file in → audio file out, tuning guide |
| 2 | Voice tuning profiles | Named, reusable voice settings; pronunciation fixes; markup for pauses |
| 3 | Read a deck | Speaker notes of each slide → one audio file per slide |
| 4 | Narrate a deck | Audio inserted in each slide, plays when the slide shows |
| 5 | Hands-free deck | Slides advance when their narration ends; re-runs only redo changed slides; optional video export |

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
- `--compare`: same text, several profiles → one file each, to pick by ear.

**Done when** profiles, lexicon and markup are covered by tests, and `docs/tts-tuning.md`
shows how to use them.

### Phase 3: Read a deck

- `foundry-tts deck synth deck.pptx`: reads each slide's speaker notes with `python-pptx`,
  applies the phase 2 markup and profile, and writes `output/<deck>/slide-01.mp3`, …
- Slides without notes are skipped and listed; hidden slides are skipped unless
  `--include-hidden`.
- A `manifest.json` next to the audio: slide number, notes hash, voice, duration, file.
- Long notes: Speech handles up to 10 minutes per request; past that, the notes are split on
  paragraph boundaries and the parts joined.

**Done when** a sample deck (made by a test, no real content) gives one audio file per slide
with notes, and the manifest is right.

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
    PowerPoint only, and can't be tested in CI.
- Re-running replaces the audio the tool inserted before (shapes it inserted are tagged), and
  leaves other media alone.

**Done when** the narrated deck opens in PowerPoint without a repair prompt, each slide plays
its narration on its own in Slide Show, and tests check the package structure.

### Phase 5: Hands-free deck

- Slide advance after the narration ends (+ a configurable gap), from the durations in the
  manifest, so the deck can run as a kiosk or self-running presentation.
- Incremental runs: only slides whose notes, profile or lexicon changed are re-synthesized
  (hash in the manifest), to save time and cost.
- Optional: export to MP4 (PowerPoint `CreateVideo` through COM, Windows only).
- Optional: `azd down` instructions and a cost note in the docs.

**Done when** a narrated deck runs start to end in Slide Show without a click, and a re-run
with one changed note re-synthesizes only that slide.

## Tuning ideas

These go into `docs/tts-tuning.md` in phase 1, then become profile settings in phase 2.

| Lever | Engine | What it does | Starting point for slide narration |
|---|---|---|---|
| Voice and model | Speech | HD (`…:DragonHDLatestNeural`) is natural and stable; MAI-Voice-2.1 (preview) is the most expressive, made for long-form narration | Try `en-US-Ava:DragonHDLatestNeural` and `en-US-Harper:MAI-Voice-2.1` |
| Speaking style | Speech | `<mstts:express-as style="…">`; MAI voices offer `narrator`, `educational`, `audiobook` | `narrator` or `educational` |
| Rate and pitch | Speech | `<prosody rate="-5%" pitch="+0%">` | Slightly slower than default (−5 to −10%) for slides |
| Pauses | Speech | `<break time="600ms"/>`, `<mstts:silence>` at sentence and paragraph ends | 300–500 ms between paragraphs |
| HD temperature | Speech (HD) | `parameters="temperature=0.6"`: lower is steadier from slide to slide | 0.5–0.7 for a consistent voice across a deck |
| Pronunciation | Speech | `<sub alias="…">`, `<phoneme>`, `<say-as interpret-as="characters">`, custom lexicon | Acronyms and product names |
| Language | Speech | `<lang xml:lang="fr-FR">` in a multilingual voice | Decks that mix languages |
| Instructions | `gpt-4o-mini-tts` | Plain-English direction of tone, pace and emotion | "Calm, confident conference presenter; clear diction; brief pause after each sentence." |
| Voice | `gpt-4o-mini-tts` | Alloy, Ash, Ballad, Coral, Echo, Sage, Shimmer, Verse, Marin, Cedar | Compare Marin, Cedar and Coral |
| Speed | `gpt-4o-mini-tts` | `speed` 0.25–4.0 | 0.95 |
| Output format | both | Sample rate and bitrate | 24 kHz mono MP3; 48 kHz only for video |
| Text hygiene | both | Notes written for reading aloud: no bullet fragments, spelled-out symbols ("→", "&", "%") | Phase 2 markup cleans the common ones |

## Open questions

- Which language(s) will the decks use? (Changes the voices to try first.)
- Is desktop PowerPoint on Windows always available where the tool runs? (Phase 4 decision.)
- Subscription and region to use for phase 1.

## Sources

Checked on Microsoft Learn on 2026-11-10:
[Speech synthesis how-to](https://learn.microsoft.com/azure/ai-services/speech-service/how-to-speech-synthesis),
[HD voices](https://learn.microsoft.com/azure/ai-services/speech-service/high-definition-voices),
[MAI-Voice in Azure Speech](https://learn.microsoft.com/azure/ai-services/speech-service/mai-voices),
[Foundry Models sold by Azure, audio models](https://learn.microsoft.com/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure#audio-models),
[Choose a speech technology](https://learn.microsoft.com/azure/architecture/data-guide/ai-services/speech-recognition-generation).
