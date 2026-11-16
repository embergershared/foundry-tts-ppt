# Tune the voice

How to make the narration sound better: try voices by ear in the Foundry playground, keep what
works as a **profile** in `foundry-tts.toml`, fix how words are said with the **pronunciation
list**, and shape the text with a little **markup**.

## 1. Try voices in the playground

Foundry portal → **Text to speech** ([aka.ms/foundry-text-to-speech](https://aka.ms/foundry-text-to-speech))
→ **Open in playground**. Paste a real paragraph of your notes and compare voices.

| Playground | Voice name in a profile (or `--voice`) |
|---|---|
| Voice **Ava**, Model **Dragon HD Latest** | `en-US-Ava:DragonHDLatestNeural` |
| Voice **Ava**, Model **Dragon HD Omni** | `en-US-Ava:DragonHDOmniLatestNeural` |
| Voice **Harper**, Model **MAI-Voice-2.1** (preview) | `en-US-Harper:MAI-Voice-2.1` |
| A standard voice | `en-US-AvaMultilingualNeural` |

The playground's **Call service** tab shows the SSML it sends. Save it to a file and use it as is:

```powershell
.venv\Scripts\foundry-tts --ssml .\tuned.xml --out .\tuned.mp3
```

## 2. Profiles

A profile is a named set of voice settings in `foundry-tts.toml`. `--list-profiles` shows them
(`*` marks the default, set in `[defaults] profile`):

```powershell
.venv\Scripts\foundry-tts --list-profiles
.venv\Scripts\foundry-tts --file .\notes.txt --profile harper-narrator
```

| Profile (shipped) | Engine | Voice and settings |
|---|---|---|
| `ava-hd` (default) | speech | Ava, Dragon HD |
| `ava-hd-steady` | speech | Ava, Dragon HD, `temperature = 0.6`, `rate = "-5%"` |
| `harper-narrator` | speech | Harper, MAI-Voice-2.1, `style = "narrator"` |
| `marin-presenter` | openai | `marin`, presenter `instructions` |

Add your own:

```toml
[profiles.andrew-calm]
engine = "speech"
voice = "en-US-Andrew:DragonHDOmniLatestNeural"
style = "calm"
temperature = 0.7
```

| Setting | Engine | What it does |
|---|---|---|
| `engine` | both | `speech` (Azure Speech voices) or `openai` (the `gpt-4o-mini-tts` deployment) |
| `voice` | both | Speech voice name, or an openai voice: alloy, ash, ballad, coral, echo, sage, shimmer, verse, marin, cedar |
| `language` | speech | SSML language (default `[speech] language`) |
| `style` | speech | `<mstts:express-as style>`. MAI Harper, Grant, Sage: `narrator`, `educational`, `audiobook`; HD voices: `calm`, `confident`, `excited`, … ([lists](https://learn.microsoft.com/azure/ai-services/speech-service/high-definition-voices)). The names a voice knows aren't checked |
| `rate`, `pitch` | speech | `<prosody>`: `"-5%"`, `"slow"`; `"+2st"`, `"-10Hz"`, `"low"` |
| `temperature` | speech, HD voices only | 0 to 1; lower is steadier from slide to slide (default 1.0 for Dragon HD) |
| `instructions` | openai | Plain-English direction of tone, pace and emotion |

`--voice`, `--language` and `--instructions` override the profile for one run. A profile that
sets something its engine or voice doesn't support (temperature on a MAI-Voice voice, `style` on
the openai engine, a rate like `slower`) is refused before anything is sent to Azure.

### Compare profiles

Repeat `--profile`: the same text goes to each, one file each, named after the profile.

```powershell
.venv\Scripts\foundry-tts --file .\notes.txt --profile ava-hd --profile harper-narrator --profile marin-presenter --out .\compare
```

## 3. Pronunciation list

The `[lexicon]` table of `foundry-tts.toml` says how to read a word or an acronym. It applies to
every profile: speech voices get `<sub alias="…">`, the openai engine gets the replacement text.
Matches are whole words and case-sensitive (`AKS` matches, `MAKS` and `aks` don't).

```toml
[lexicon]
AKS = "A K S"
SaaS = "sass"
"Q&A" = "Q and A"
```

For a deck's own words, keep a separate file with a `[lexicon]` table and add it with
`--lexicon .\deck-words.toml`; its entries win over the settings file's.

## 4. Markup in the text

| Write | Effect |
|---|---|
| `// note to self` (a whole line) | Not spoken |
| `[pause 1s]`, `[pause 750ms]`, `[pause 1.5s]` | A pause (at most 20 s); the openai engine gets "..." instead |
| A new paragraph (new line) | A pause of `[speech] paragraph_break_ms` (400 ms) |
| `[excited] Great news!` | Left as is: HD voices read a style word in brackets as a style tag |

Stress (`*word*`) isn't offered: Azure's `<emphasis>` works on three standard voices only, none of
the HD or MAI voices.

Speaker notes read from a deck (`foundry-tts deck synth`) are also cleaned of presenter cues:
`(Click)` becomes a pause, emoji, bullets and quotes are dropped, `10–15` is read "10 to 15". See
[getting-started.md](getting-started.md#5-narrate-a-decks-speaker-notes).

## 5. What each voice family honors

The docs and the service disagree, so this was measured on 2026-11-11 (eastus2) by comparing
audio lengths: an 8 s `<break>`, a `<sub>` with a long alias, `<prosody rate="-40%">`.

| Family | Pauses (`<break>`) | Pronunciation (`<sub>`) | Rate (`<prosody>`) | Temperature |
|---|---|---|---|---|
| Dragon HD | Yes | Yes | Yes (docs say no) | Yes |
| Dragon HD Omni | Yes (docs say no) | Yes | Yes (docs say no) | Yes |
| MAI-Voice | **Ignored**: the tool sends none and warns about `[pause]` | Yes | Yes | Refused |
| Standard | Yes | Yes | Yes | Refused |

Styles were accepted by all families; whether they change the delivery is for your ear.
Listen to the result: the service may change, and these checks only measured length.

## 6. Other levers

| Lever | How | Starting point for slides |
|---|---|---|
| Steadiness | `temperature` on an HD profile | 0.5–0.7 |
| Pronunciation (HD) | In hand-written SSML: `parameters="enhancePronunciation=true"` on `<voice>`, `<say-as interpret-as="characters">`, `<phoneme>` (Dragon HD, not Omni) | Acronyms and product names |
| Language | `language` or `--language fr-FR` with a voice of that language; `<lang xml:lang>` in hand-written SSML | Decks that mix languages |
| Audio format | `[speech] output_format` (e.g. `audio-48khz-192kbitrate-mono-mp3`), `[openai] response_format` | 24 kHz mono MP3; 48 kHz for video |
| Text | Write notes for the ear: full sentences, symbols spelled out ("percent", "and"), numbers as they should be said | — |

`--save-ssml` writes the SSML the tool sent next to the audio, as a starting point for a
hand-written file.
