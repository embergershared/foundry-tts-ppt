# Tune the voice

How to make the narration sound better. Tune by ear in the Foundry playground first, then carry
the settings over to the tool. Phase 2 of the [plan](plan.md) turns them into named profiles.

## 1. Try voices in the playground

Foundry portal → **Text to speech** ([aka.ms/foundry-text-to-speech](https://aka.ms/foundry-text-to-speech))
→ **Open in playground**. Paste a real paragraph of your notes and compare voices.

| Playground | Tool (`--voice` or `[speech] voice`) |
|---|---|
| Voice **Ava**, Model **Dragon HD Latest** | `en-US-Ava:DragonHDLatestNeural` |
| Voice **Harper**, Model **MAI-Voice-2.1** (preview) | `en-US-Harper:MAI-Voice-2.1` |
| A standard voice | `en-US-AvaMultilingualNeural` |

The playground's **Call service** tab shows the SSML it sends. Save it to a file and use it as is:

```powershell
.venv\Scripts\foundry-tts --ssml .\tuned.xml --out .\tuned.mp3
```

## 2. Compare engines and voices on the same text

```powershell
.venv\Scripts\foundry-tts --file .\notes.txt --out .\ava-hd.mp3
.venv\Scripts\foundry-tts --file .\notes.txt --voice en-US-Harper:MAI-Voice-2.1 --out .\harper-mai.mp3
.venv\Scripts\foundry-tts --file .\notes.txt --engine openai --voice marin --out .\marin.mp3
.venv\Scripts\foundry-tts --file .\notes.txt --engine openai --voice cedar --out .\cedar.mp3 `
  --instructions "Warm, upbeat keynote speaker. Slightly slower than normal; stress the key numbers."
```

## 3. What to change

| Lever | Engine | How | Starting point for slides |
|---|---|---|---|
| Voice and model | speech | `--voice`. Dragon HD: natural, picks its own emotion. MAI-Voice-2.1: most expressive, made for long narration (preview) | `en-US-Ava:DragonHDLatestNeural`, then `en-US-Harper:MAI-Voice-2.1` |
| Pauses | speech | `[speech] paragraph_break_ms` (a `<break>` between paragraphs); `<break time="600ms"/>` in hand-written SSML | 300–500 ms |
| Steadiness | speech, Dragon HD | `<voice name="…" parameters="temperature=0.6">` in SSML: lower is steadier from slide to slide (default 1.0) | 0.5–0.7 |
| Style | speech, MAI-Voice and standard voices | `<mstts:express-as style="narrator">…</mstts:express-as>`; Harper, Grant and Sage (MAI) offer `narrator`, `educational`, `audiobook`. Not for Dragon HD | `narrator` |
| Speed and pitch | speech, standard and MAI voices | `<prosody rate="-5%" pitch="+0%">…</prosody>`. **Dragon HD voices ignore `<prosody>`** | −5 to −10 % |
| Pronunciation | speech | `<sub alias="A K S">AKS</sub>`, `<say-as interpret-as="characters">`, `<phoneme>`; Dragon HD: `parameters="enhancePronunciation=true"`, lexicon alias entries only | Acronyms and product names |
| Language | speech | `--language fr-FR` with a voice of that language; `<lang xml:lang="fr-FR">` in a multilingual voice | Decks that mix languages |
| Tone | openai | `--instructions` or `[openai] instructions`: plain English about tone, pace, emotion, pauses | "Calm, confident conference presenter …" (the default) |
| Voice | openai | `--voice`: alloy, ash, ballad, coral, echo, sage, shimmer, verse, marin, cedar | Compare marin, cedar, coral |
| Audio format | both | `[speech] output_format` (e.g. `audio-48khz-192kbitrate-mono-mp3`), `[openai] response_format` | 24 kHz mono MP3; 48 kHz for video |
| Text | both | Write notes for the ear: full sentences, symbols spelled out ("percent", "and"), numbers as they should be said | — |

SSML support differs by voice family: see
[HD voices: supported SSML](https://learn.microsoft.com/azure/ai-services/speech-service/high-definition-voices#supported-and-unsupported-ssml-elements-for-azure-speech-hd-voices).
An unsupported element is ignored or refused by Azure, so listen to the result.

## 4. Keep what works

- Put the chosen voice, language, pause and instructions in `foundry-tts.toml`.
- Keep a tuned SSML file next to your notes (`--save-ssml` writes the one the tool built, as a
  starting point).
