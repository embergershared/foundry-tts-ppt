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
| `--voice`, `--language`, `--instructions` | Override the profile for this run (`--instructions`: openai profiles, which take at most 4096 characters of text) |
| `--lexicon <file>` | Adds a deck's own pronunciation list (a `[lexicon]` table) to the settings file's |
| `--out`, `--overwrite` | Where the audio goes (default: `output\<time>-<profile>.mp3`, gitignored; a folder when comparing profiles); existing files are kept unless `--overwrite` |
| `--save-ssml` | Also saves the SSML sent to Speech next to the audio, to reuse or tune it |
| `--verbose` | DEBUG logs |

Each step writes one JSON log line to the console; the last one gives the file path, size and
length. When Azure refuses a request, the tool stops with the HTTP status and Azure's message,
exits with code 1, and writes no file.

To tune the voice, see [tts-tuning.md](tts-tuning.md).

## 5. Run the checks

```powershell
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
.venv\Scripts\python -m pytest -q
```

The tests run offline: Azure and the sign-in are replaced by stubs. CI runs the same checks.

## Settings

| Where | What |
|---|---|
| `foundry-tts.toml` | Voices, language, audio format, pause length, tone instructions, timeout, output folder |
| `.env` (from `.env.example`, gitignored) | The deployed resource: `FOUNDRY_RESOURCE_ID`, `FOUNDRY_REGION`, `FOUNDRY_OPENAI_ENDPOINT`, `FOUNDRY_TTS_DEPLOYMENT`, optional `FOUNDRY_SPEECH_ENDPOINT` |

Variables already set in the environment win over `.env`.

## Remove the resources

```powershell
azd down --purge
```

This deletes the resource group and purges the Foundry resource (no way back).
