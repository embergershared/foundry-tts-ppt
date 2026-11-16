# foundry-tts-ppt

## Overview

<!-- Keep this section: a few lines on what the project does and for whom. The details go in
     docs/. -->

Generates voice-over audio for PowerPoint slides from their speaker notes, using Microsoft Foundry text-to-speech.

## Quick start

<!-- Keep this section: the few commands that take a new user from a clone to a first run,
     each with where it runs. The full walkthrough stays in docs/getting-started.md. -->

PowerShell (workstation), in the clone, with Python 3.13, the Azure CLI and `azd`:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install --require-hashes -r requirements-dev.lock
.venv\Scripts\python -m pip install --no-deps --no-build-isolation -e .
az login; azd auth login
azd env new tts-dev --location eastus2
azd env set AZURE_PRINCIPAL_ID (az ad signed-in-user show --query id -o tsv)
azd provision
azd env get-values | Out-File -Encoding utf8 .env
.venv\Scripts\foundry-tts --text "Hello from Microsoft Foundry."
.venv\Scripts\foundry-tts deck synth .\deck.pptx
```

The audio files are written to `output\` (for a deck: one per slide, and a manifest). Details: [docs/getting-started.md](docs/getting-started.md).

## Contents

<!-- Keep this README short: the Overview and Quick start above, then this table of contents of
     the pages, the license and the personal-project note. Background, how-tos and long
     explanations go in docs/, one page per topic. -->

**Use it**

| Page | What it covers |
|---|---|
| [docs/getting-started.md](docs/getting-started.md) | **Start here:** build, run and test the project locally |
| [docs/tts-tuning.md](docs/tts-tuning.md) | Make the voice sound better: voices, pauses, style, tone |
| [docs/plan.md](docs/plan.md) | The plan: phases, choices, voice tuning ideas |
| [docs/powershell-prototype.md](docs/powershell-prototype.md) | A tested PowerShell prototype that narrates a deck through PowerPoint (Windows) |
| [docs/SUPPORT.md](docs/SUPPORT.md) | Questions, bugs, and what support to expect |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | Changes |

**Contribute**

Every change starts with an issue, gets its own `<type>/<issue>-<slug>` branch, and reaches
`main` only through a PR that closes the issue.

| Page | What it covers |
|---|---|
| [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md), [docs/CODE_OF_CONDUCT.md](docs/CODE_OF_CONDUCT.md) | How to contribute |
| [.github/copilot-instructions.md](.github/copilot-instructions.md) | The full rules, for people and AI coding assistants |
| [docs/ci-cd.md](docs/ci-cd.md) | CI/CD workflows, public logs, ruleset, security settings, repository variables |
| [docs/supply-chain.md](docs/supply-chain.md) | Package feeds, age gate, lock files |
| [docs/database.md](docs/database.md) | Database migrations, backups, rollback |
| [docs/decisions/](docs/decisions/) | Decision records |
| [docs/SECURITY.md](docs/SECURITY.md) | Reporting a vulnerability |

## License

[MIT](LICENSE)

> [!NOTE]
> This is a personal project, shared as is to help others. It is not an official Microsoft
> product and is not supported by Microsoft. Review and test it before using any part of it
> in your environment. See [docs/SUPPORT.md](docs/SUPPORT.md).
