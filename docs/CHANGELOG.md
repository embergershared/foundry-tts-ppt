# Changelog

What changed for users of foundry-tts-ppt, newest first. Each merged PR adds its line under
**Unreleased** (with its issue number); a release moves them under a dated version.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased

### Added
- `foundry-tts voice list`: every Azure Speech voice the resource offers (over a thousand, MAI-Voice and Dragon HD included), with its gender, family, model, status and styles, filtered by `--language`, `--gender`, `--family` and `--search`; `--json` for scripts. The demo's tuning window gets a **Pick…** button next to Voice that searches and filters that list, and shows the styles of the chosen voice under Style (#30).
- Demo launcher: a tuning window opens first, with the last run's choices, to pick the deck, the voice profile and its settings, and the run options (auto-advance, MP4, Slide Show); it plays a one-slide sample, saves the settings as a new profile, and checks them before narrating. `-SkipTuning` keeps the file picker (#27).
- `foundry-tts`: `--style`, `--rate`, `--pitch` and `--temperature` override a profile for one run, as `--voice` does; `deck sample` speaks one slide to try a voice on a deck; `profile list|check|save` give the profiles as JSON and save a new one in `foundry-tts.toml` (#27).
- Profile `andrew-hd`: a male Dragon HD voice (Andrew) (#21).
- `scripts/Start-Demo.ps1`: pick a deck in a file picker and get it back ready to play, narrated and self-running, straight in Slide Show; `docs/demo.md` is the runbook for a customer demo (#21).
- `foundry-tts deck narrate --auto-advance`: the deck runs on its own, each slide moving on when its narration ends; `--video` also exports it to MP4 (#13).
- `foundry-tts deck narrate deck.pptx`: a copy of the deck with each slide's audio embedded, starting on its own in Slide Show; made through desktop PowerPoint, which keeps a sensitivity label's protection (#12).
- `foundry-tts deck synth deck.pptx`: one audio file per slide from its speaker notes, with presenter cues cleaned out, and a `manifest.json`; sensitivity-labeled decks are read through desktop PowerPoint (#11).
- Voice profiles in `foundry-tts.toml` (`--profile`, repeat it to compare), a pronunciation list (`[lexicon]`, `--lexicon`), and markup in the text: `//` comment lines and `[pause 1s]` (#10).
- `foundry-tts` command: text typed, from a file or piped in becomes an audio file made by Foundry text to speech, with Azure Speech voices or `gpt-4o-mini-tts`; `infra/` deploys the Foundry resource with `azd`; voice tuning guide (#9).
- The plan, and a PowerShell prototype that narrates a deck's speaker notes with Azure Speech through PowerPoint (#3).
- Repository created from [embergershared/repo-template](https://github.com/embergershared/repo-template).

### Changed
- `foundry-tts`: the default profile is `andrew-hd` (a male voice) instead of `ava-hd`, for text, decks and the demo launcher; `--profile ava-hd` (or the demo's `-VoiceProfile ava-hd`) brings Ava back (#21).
- `foundry-tts deck synth` and `deck narrate`: they write the full path of what they made on stdout, for scripts; logs stay on stderr (#21).
- `foundry-tts deck synth` and `deck narrate`: a rerun only synthesizes the slides that changed and replaces the files it wrote before; `--overwrite` makes everything again (#13).
- `foundry-tts`: text longer than one request is split and the MP3 parts are joined, instead of being refused (#11).
- `foundry-tts`: profiles replace `--engine`; output files are named after the profile (#10).
- README: it opens with an Overview (what the project does) and a Quick start; the personal-project note is at the bottom (#5).
- Plan: it covers sensitivity-labeled decks, which `python-pptx` can't open, and the cleanups real speaker notes need before they are spoken (#15).
- Getting started: a "What it costs" section with what one run of a real 15-slide deck costs per profile, measured from the requests the tool builds (#23).

### Fixed
- `foundry-tts deck narrate`: a deck with a long file name no longer fails at the end with "Deck not found". PowerPoint can't save a path over 259 characters and had cut the copy's name to `.narrated.ppt`; long output names are now shortened to fit (`[deck] max_path_chars`, `min_name_chars`), paths that can't fit are refused before any Azure call, and the tool checks the copy and the video are where PowerPoint was told to save them (#25).
