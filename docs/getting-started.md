# Getting started

From a clone to a first audio file: set up Python, deploy the Foundry resource, then turn text
into speech. Everything runs in **PowerShell (workstation)**, in the repository folder.

## 1. Prerequisites

| Tool | Why | Check |
|---|---|---|
| Python 3.13 (`py` launcher) | The tool | `py -3.13 --version` |
| Azure CLI | Sign-in (`az login`); the tool uses its token | `az version` |
| Azure Developer CLI (`azd`) | Deploys `infra/` | `azd version` |
| An Azure subscription where you can create resources **and role assignments** (Owner, or Contributor + User Access Administrator) | The deployment gives you the *Cognitive Services User* role | — |

## 2. Python environment

```powershell
Set-Location '<clone>'
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install --require-hashes -r requirements-dev.lock
.venv\Scripts\python -m pip install --no-deps --no-build-isolation -e .
```

The last line installs the `foundry-tts` command into `.venv` (the code stays in `src/`, so edits
take effect at once). Packages come only from the approved feed and are locked with hashes:
see [supply-chain.md](supply-chain.md).

## 3. Deploy the Foundry resource

`infra/main.bicep` creates, in resource group `rg-<environment>`:

| Resource | Settings |
|---|---|
| Foundry resource (`Microsoft.CognitiveServices/accounts`, kind `AIServices`, S0) | Custom subdomain, **keys off** (Microsoft Entra ID only), public network access |
| Foundry project `proj-tts` | — |
| Model deployment `gpt-4o-mini-tts` (version 2025-12-15, GlobalStandard, capacity 1) | Only for openai profiles (`marin-presenter`) |
| Role *Cognitive Services User* for you, on the Foundry resource | Lets the tool call Speech and the model |

Azure Speech voices (HD, MAI-Voice) need no deployment. Use **eastus2**: it has the Dragon HD
and MAI-Voice voices and `gpt-4o-mini-tts` (swedencentral has no `gpt-4o-mini-tts`).

```powershell
az login
azd auth login
azd env new tts-dev --subscription (az account show --query id -o tsv) --location eastus2
azd env set AZURE_PRINCIPAL_ID (az ad signed-in-user show --query id -o tsv)
azd provision --preview     # what would be created; changes nothing
azd provision               # creates the resources (costs: pay per use)
```

Check the subscription that `azd env new` shows before `azd provision`.

- `AZURE_PRINCIPAL_ID` is the user who gets the role. Without it, no role is assigned and the tool
  gets HTTP 401/403.
- If `azd` fails with "Downloading Bicep" (a proxy blocks the download), point it at the Bicep
  that comes with the Azure CLI: `$env:AZD_BICEP_TOOL_PATH = "$HOME\.azure\bin\bicep.exe"`
  (run `az bicep install` first if the file is missing).
- A new role assignment can take a few minutes to apply.

Then write the outputs (names and endpoints, no secrets) to `.env`, which the tool reads:

```powershell
azd env get-values | Out-File -Encoding utf8 .env
```

To use an existing Foundry resource instead, copy `.env.example` to `.env` and fill in its values
(you need the *Cognitive Services User* role on it).

## 4. Make an audio file

```powershell
.venv\Scripts\foundry-tts --text "Welcome to the quarterly review."
.venv\Scripts\foundry-tts --file .\notes.txt --out .\intro.mp3
Get-Content .\notes.txt | .venv\Scripts\foundry-tts --profile marin-presenter
```

| Option | What it does |
|---|---|
| `--text`, `--file`, `--ssml`, or a pipe | The text to say (a file is read as UTF-8). `--ssml` sends a hand-written SSML file as is (speech profiles only) |
| `--profile <name>` | The voice profile from `foundry-tts.toml` (default `ava-hd`). Repeat it to compare profiles: one file each. `--list-profiles` lists them |
| `--voice`, `--language`, `--instructions` | Override the profile for this run (`--instructions`: openai profiles) |
| `--lexicon <file>` | Adds a deck's own pronunciation list (a `[lexicon]` table) to the settings file's |
| `--out`, `--overwrite` | Where the audio goes (default: `output\<time>-<profile>.mp3`, gitignored; a folder when comparing profiles); existing files are kept unless `--overwrite` |
| `--save-ssml` | Also saves the SSML sent to Speech next to the audio, to reuse or tune it |
| `--verbose` | DEBUG logs |

Each step writes one JSON log line to the console; the last one gives the file path, size and
length. When Azure refuses a request, the tool stops with the HTTP status and Azure's message,
exits with code 1, and writes no file.

Text longer than one request takes (`[speech] max_chars_per_request`, 6,000 characters, about
6 minutes; 4,096 for openai profiles) is split between paragraphs, or sentences, and the MP3
parts are joined into one file.

To tune the voice, see [tts-tuning.md](tts-tuning.md).

## 5. Narrate a deck's speaker notes

```powershell
.venv\Scripts\foundry-tts deck synth .\deck.pptx
.venv\Scripts\foundry-tts deck synth .\deck.pptx --profile harper-narrator --out .\narration
```

This writes, in `output\<deck name>\`, one audio file per slide that has notes
(`slide-01.mp3`, `slide-04.mp3`, …) and a `manifest.json`. The deck itself is never changed.

| Slide | What happens |
|---|---|
| With notes | Its notes are cleaned (below), then said with the profile: `slide-NN.mp3` |
| Without notes, or only `//` comment lines | Skipped, listed in the manifest as `no notes` |
| Hidden | Skipped (`hidden`), unless `--include-hidden` |

Notes are written for a presenter, so they are cleaned before they are said; each cleanup is
logged with its slide:

| In the notes | Said as |
|---|---|
| `(Click)` | A pause of `[deck] cue_pause_ms` (500 ms) |
| An emoji | Nothing |
| A `- `, `• ` or `* ` bullet at the start of a line | The item, as its own paragraph (a short pause between items) |
| `“` `”` `"` quotes | Nothing |
| `10–15` (en or em dash between numbers) | "10 to 15" |
| `the end .` | "the end." |

The `//` comments, `[pause 1s]` and the pronunciation list of
[tts-tuning.md](tts-tuning.md) work in notes too.

| Option | What it does |
|---|---|
| `--profile`, `--voice`, `--language`, `--instructions`, `--lexicon` | As for text, one profile |
| `--out <folder>` | Where the audio and the manifest go (default `output\<deck name>\`) |
| `--include-hidden` | Also narrate hidden slides |
| `--reader auto\|python-pptx\|powerpoint` | How the deck is read (below) |
| `--overwrite`, `--save-ssml` | As for text (`slide-NN.ssml`) |

**Labeled decks.** A deck protected by a Microsoft Purview sensitivity label (or a password) is
encrypted, which `python-pptx` can't open. The tool sees it from the file's first bytes and reads
it through **desktop PowerPoint** instead (Windows only): read-only, without a window, nothing
saved, and PowerPoint is quit afterwards if the tool started it. PowerPoint opens it with your
own rights, so you must be allowed to open it. `--reader powerpoint` forces this for any deck;
on another OS a labeled deck stops with a message saying why.

Everything is checked before the first Azure call (notes, markup, existing files). If a slide
fails, the run stops and names it; the slides before it are kept and no manifest is written.

`manifest.json` lists, for each slide said: its number, file, length in seconds, size, number of
requests, the cleanups, and a `hash`, the sha256 of exactly what was sent to Azure. The hash
changes when the notes, the profile, the lexicon or the settings change. Skipped slides are listed
with their reason.

## 6. Put the narration in the deck

```powershell
.venv\Scripts\foundry-tts deck narrate .\deck.pptx
.venv\Scripts\foundry-tts deck narrate .\deck.pptx --skip-synth    # reuse the audio already made
```

`deck narrate` does what `deck synth` does, then saves a copy of the deck,
`output\<deck name>\<deck name>.narrated.pptx`, with each slide's audio embedded. **It needs
desktop PowerPoint on Windows**, which does the embedding
([decision 0002](decisions/0002-narrate-decks-through-powerpoint.md)). The source deck is opened
read-only and never changed.

In the narrated copy, each slide with notes has one audio shape:

- embedded in the file (not linked), so the deck can be shared on its own;
- placed just right of the slide (`[deck] off_slide_margin_points`), so it never covers the
  content, and hidden during the show;
- set to **start by itself** as the slide shows, before the slide's own click animations.

| Option | What it does |
|---|---|
| The `deck synth` options | Make the audio first (same defaults) |
| `--skip-synth` | Embed the audio and `manifest.json` already in the out folder; no Azure call |
| `--deck-out <file>.pptx` | Where the narrated copy goes |
| `--overwrite` | Replace an earlier narrated copy (and the audio, unless `--skip-synth`) |

Running it again on a narrated copy replaces the audio the tool put in (shapes named
`[deck] audio_shape_name`, or carrying its tag) and leaves other media alone; a slide that has no
notes any more loses its old narration.

A deck with a **sensitivity label** stays encrypted: PowerPoint saves the copy with the same
protection (checked on a real labeled deck). If a copy of an encrypted deck comes out
unencrypted, the tool logs a warning; check its label before sharing it.

Open the copy and start the Slide Show to listen: each slide's narration plays on its own; you
still click to go to the next slide.

## 7. Run the checks

```powershell
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
.venv\Scripts\python -m pytest -q
```

The tests run offline: Azure and the sign-in are replaced by stubs. CI runs the same checks.
Decks are made by the tests (`tests/decks.py`: a Contoso deck with the quirks of real notes).

Two opt-in checks need desktop PowerPoint on Windows and are skipped otherwise (and in CI):

```powershell
$env:FOUNDRY_TTS_POWERPOINT_TESTS = "1"                # read and narrate the test deck in PowerPoint
$env:FOUNDRY_TTS_ACCEPTANCE_DECK = "<path to a real deck>"  # optional: also read a real deck
.venv\Scripts\python -m pytest -q tests/test_powerpoint.py
```

Keep a real deck outside the repository; the check prints nothing from its notes. The narration
check embeds generated tones (no Azure), then reads the saved package: one audio part per
narrated slide, set to start by itself, and a rerun that replaces it.

## Settings

| Where | What |
|---|---|
| `foundry-tts.toml` | Voices, language, audio format, pause length, tone instructions, longest request, `(Click)` pause, the narration shape's name and place, timeout, output folder |
| `.env` (from `.env.example`, gitignored) | The deployed resource: `FOUNDRY_RESOURCE_ID`, `FOUNDRY_REGION`, `FOUNDRY_OPENAI_ENDPOINT`, `FOUNDRY_TTS_DEPLOYMENT`, optional `FOUNDRY_SPEECH_ENDPOINT` |

Variables already set in the environment win over `.env`.

## Remove the resources

```powershell
azd down --purge
```

This deletes the resource group and purges the Foundry resource (no way back).
