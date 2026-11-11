# Changelog

What changed for users of foundry-tts-ppt, newest first. Each merged PR adds its line under
**Unreleased** (with its issue number); a release moves them under a dated version.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased

### Added
- `foundry-tts deck synth deck.pptx`: one audio file per slide from its speaker notes, with presenter cues cleaned out, and a `manifest.json`; sensitivity-labeled decks are read through desktop PowerPoint (#11).
- Voice profiles in `foundry-tts.toml` (`--profile`, repeat it to compare), a pronunciation list (`[lexicon]`, `--lexicon`), and markup in the text: `//` comment lines and `[pause 1s]` (#10).
- `foundry-tts` command: text typed, from a file or piped in becomes an audio file made by Foundry text to speech, with Azure Speech voices or `gpt-4o-mini-tts`; `infra/` deploys the Foundry resource with `azd`; voice tuning guide (#9).
- The plan, and a PowerShell prototype that narrates a deck's speaker notes with Azure Speech through PowerPoint (#3).
- Repository created from [embergershared/repo-template](https://github.com/embergershared/repo-template).

### Changed
- `foundry-tts`: text longer than one request is split and the MP3 parts are joined, instead of being refused (#11).
- `foundry-tts`: profiles replace `--engine`; output files are named after the profile (#10).
- README: it opens with an Overview (what the project does) and a Quick start; the personal-project note is at the bottom (#5).
