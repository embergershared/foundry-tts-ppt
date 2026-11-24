# Voice styles, sound effects and custom voices

How to set the tone of a sentence with a **style tag**, add a **sound effect** (a laugh, a sigh),
and make a **custom voice** from a real person's recordings. Sources: Microsoft Learn, checked on
2026-11-23 (links in [Sources](#sources)).

## 1. Style tags in the text

With an HD voice, a word in square brackets at the start of a sentence sets its tone:

```text
[joking] Well, if weekends were any shorter, I'd want a refund.
[curious] Have you ever noticed how time feels slower on rainy days?
[relieved] Anyway, it's nice to just talk without any pressure.
```

| Rule | Detail |
|---|---|
| Voices | **Dragon HD** (`en-US-Ava:DragonHDLatestNeural`) and **Dragon HD Omni** (`en-US-Ava:DragonHDOmniLatestNeural`) only. Don't use them with MAI, standard or openai voices: those may read the word aloud (not verified). |
| Language | Styles work on **English** text only. Sound effects work in all languages on Dragon HD Omni. |
| Placement | One tag at the start of each sentence you want to color. Write the tag in lower case, as listed below. |
| It's a hint | The model applies a style only when it fits the meaning of the sentence: `[happy]` on sad news may barely change anything. Listen to the result. |
| In this tool | Brackets reach the voice unchanged, except `[pause 1s]` ([tts-tuning.md](tts-tuning.md#4-markup-in-the-text)). They work in `--text`, `--file` and speaker notes. |
| Whole slide | To give a whole request one style, use the profile setting `style` (`<mstts:express-as>`) instead of a tag on every sentence. |

### Styles

**In both Dragon HD and Dragon HD Omni (52):**

`amazed`, `amused`, `angry`, `annoyed`, `anxious`, `appreciative`, `calm`, `cautious`, `concerned`,
`confident`, `confused`, `curious`, `defeated`, `defensive`, `defiant`, `determined`,
`disappointed`, `disgusted`, `doubtful`, `encouraging`, `excited`, `fast`, `fearful`, `frustrated`,
`happy`, `hesitant`, `hurt`, `impatient`, `impressed`, `intrigued`, `laughing`, `optimistic`,
`panicked`, `pleading`, `quiet`, `reassuring`, `reflective`, `remorseful`, `resigned`, `sad`,
`sarcastic`, `secretive`, `serious`, `shouting`, `shy`, `skeptical`, `slow`, `surprised`,
`suspicious`, `sympathetic`, `upset`, `urgent`

**Dragon HD Omni only (9):** `ecstatic`, `joking`, `painful`, `panting`, `proud`, `relieved`,
`shocked`, `struggling`, `terrified`

**Dragon HD only:** `whispering` (the SSML page also lists it for Dragon HD Omni; the HD voices
page doesn't)

### Sound effects (paralinguistics)

Put the tag where the sound should be. All six work on every HD voice.

| Tag | Sound |
|---|---|
| `[laughter]` | A short laugh |
| `[coughing]` | A cough |
| `[throat_clearing]` | Clearing the throat |
| `[breathing]` | An audible breath |
| `[sighing]` | A sigh |
| `[yawning]` | A yawn |

```text
[laughter] Don't worry, we'll get you a table, no problem!
```

### Styles that suit a presentation

| Moment in the talk | Try |
|---|---|
| Opening, welcome | `confident`, `happy`, `encouraging` |
| A key result | `excited`, `impressed`, `proud` (Omni) |
| A risk or a problem | `serious`, `concerned`, `cautious` |
| A question to the room | `curious`, `intrigued` |
| Reassuring after a problem | `reassuring`, `calm`, `optimistic` |
| A light moment | `amused`, `joking` (Omni), then `[laughter]` |
| Closing, call to action | `determined`, `urgent`, `encouraging` |

`fast`, `slow` and `quiet` change the delivery, not the feeling. Use them for an aside or to
stress a line.

### Other voice families

| Family | How to set a style |
|---|---|
| MAI-Voice (e.g. `en-US-Harper:MAI-Voice-2.1`) | The profile's `style`, from that voice's own list (e.g. `narrator`, `educational`, `audiobook` on Harper; `joyful`, `hopeful`, `softvoice`, … on others). See the voice list in [Language and voice support](https://learn.microsoft.com/azure/ai-services/speech-service/language-support?tabs=tts). |
| Standard (e.g. `en-US-AvaMultilingualNeural`) | The profile's `style`, for the voices that have styles (same list page) |
| openai (`gpt-4o-mini-tts`) | The profile's `instructions`, in plain words ("warm, upbeat presenter") |

## 2. Custom voices

A custom voice is a voice made from one real person (the **voice talent**). Azure Speech has two
kinds:

| | Personal voice | Professional voice |
|---|---|---|
| Made from | One clean 5–90 s recording | Studio recordings with their transcripts (hundreds of sentences) |
| Training | None: ready in minutes | About 10 compute hours; 4 trainings at a time per S0 resource |
| Result | A `speakerProfileId`, used with a base voice model | A voice model, deployed to its own endpoint |
| Hosting | No deployment | An endpoint, billed while it runs (up to 50 per S0 resource) |
| Style tags | Yes, with the base model `DragonHDOmniLatestNeural` | Only if trained with **Neural - HD** or **Neural - Multi style** (preset or custom styles) |
| Best for | Trying a voice, a person's own voice | A brand voice that must sound the same everywhere |

### What both need

1. **Limited access approval.** Custom voice is a limited-access feature: apply at
   [aka.ms/customneural](https://aka.ms/customneural) and wait for approval. Without it the
   options don't appear.
2. **A Foundry project on a Standard (S0) resource** in a region that offers it (Speech regions
   table: **Custom voice training** or **Personal voice** column). The free tier (F0) can't.
3. **Written permission from the voice talent,** and a recording of them reading the **consent
   statement**, with their name and the company name in it. Share Microsoft's
   [disclosure for voice talent](https://learn.microsoft.com/azure/ai-foundry/responsible-ai/speech-service/text-to-speech/disclosure-voice-talent)
   before they record. Record it with the same microphone, room and tone as the voice data.

### Make a personal voice

1. In [Foundry](https://ai.azure.com) (New Foundry on), open the project → **Discover** →
   **Azure Speech** → under **Customize**, **Personal voice**. Fill in the basic details (name,
   language).
2. **Register voice talent:** upload the consent recording (`.mp3` or `.wav`) and type the talent
   name and company name exactly as spoken. Wait for **Succeeded**.
3. **Upload the prompt:** a 5–90 s recording of the same person speaking naturally, no music or
   noise (mp3 or wav, 16 to 48 kHz).
4. When the customization shows **Succeeded**, open it: **Profile ID** under **Model attributes**
   is the `speakerProfileId`. **Open in Playground** to try it.
5. Use it in SSML with a base model as the voice name (`DragonHDOmniLatestNeural` for style tags,
   `DragonLatestNeural` for the closest likeness, `PhoenixLatestNeural` for the lowest latency):

   ```xml
   <speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis"
          xmlns:mstts="http://www.w3.org/2001/mstts" xml:lang="en-US">
     <voice name="DragonHDOmniLatestNeural">
       <mstts:ttsembedding speakerProfileId="<speaker-profile-id>">
         [confident] Welcome, everyone. [laughter] Let's get started.
       </mstts:ttsembedding>
     </voice>
   </speak>
   ```

   With this tool: `foundry-tts --ssml .\personal.xml --out .\personal.mp3`. Profiles and the deck
   commands don't take a `speakerProfileId` yet.

### Make a professional voice

1. **Plan the voice:** write a short persona brief (who speaks, how), pick a recording script that
   matches your use (statements, questions, exclamations), and record in a quiet studio with a
   steady volume, pace and tone.
2. **Start:** Foundry → project → **Discover** → **Azure Speech** → under **Customize**,
   **Professional voice**. **Basic details:** model *Azure Speech - Text to Speech*, type
   *Professional voice*, the talent's gender, the training language, a voice name.
3. **Register voice talent:** pick the target scenarios, upload the consent recording, type the
   talent name and company name as spoken. Wait for **Succeeded**. (**Download sample data** on
   this step gives a sample consent and training set.)
4. **Training data:** **Create new dataset** → **Add data** → pick the data type:

   | Data type | Processed as |
   |---|---|
   | Individual utterances + matching transcript | Segmented |
   | Long audio + transcript | Segmented, or Contextual (keeps natural intonation; some languages) |
   | Audio only (the service writes the transcript) | Segmented, or Contextual |

   Upload from your computer or a Blob URL, then fix what **Data preview** rejects. Don't mix
   segmented and contextual data.
5. **Training method and version:**

   | Method | Gives |
   |---|---|
   | **Neural - HD** | An HD voice in the training language, for natural, conversational speech |
   | **Neural - Default** | A voice in the training language |
   | **Neural - Multi lingual** | A voice that also speaks other languages, from one-language data |
   | **Neural - Multi style** | A voice with several styles: at least 300 general sentences, plus preset styles (en-US: `angry`, `cheerful`, `excited`, `friendly`, `hopeful`, `sad`, `shouting`, `terrified`, `unfriendly`, `whispering`) and/or custom styles of at least 100 sentences each |

   The portal says whether a dataset is big enough for the method and version you pick.
6. **Review** → accept the cost and the terms → **Submit**. Follow it in **Build** → **Services**
   → **Customizations**; canceling a training is free.
7. **Deploy:** open the trained model → **Deploy** → a deployment name and the endpoint type:
   **High performance** (real-time, high volume; about 5 min to start) or **Fast resume** (content
   creation, occasional use; under a minute). Accept the terms and the hosting cost.
8. **Use it:** the deployment shows the **Voice name** and the endpoint ID (`deploymentId`). Put the
   voice name in `<voice name="…">` and send the request to the custom endpoint
   (`https://<region>.voice.speech.microsoft.com/cognitiveservices/v1?deploymentId=<endpoint-id>`),
   with the same resource. To switch to a newer model, deploy it to a **new** endpoint, move the
   traffic, and delete the old one after a day.

   With this tool, `FOUNDRY_SPEECH_ENDPOINT` replaces the regional URL, so it can point at the
   custom endpoint; this hasn't been tried yet.

## Sources

Microsoft Learn (Azure Speech in Foundry Tools):
- [High-definition voices](https://learn.microsoft.com/azure/ai-services/speech-service/high-definition-voices): style tags, sound effects, Dragon HD and Dragon HD Omni lists
- [SSML: speaking styles and paralinguistics](https://learn.microsoft.com/azure/ai-services/speech-service/speech-synthesis-markup-voice#use-speaking-styles,-paralinguistics-and-roles)
- [What is custom voice?](https://learn.microsoft.com/azure/ai-services/speech-service/custom-neural-voice) and [limited access](https://learn.microsoft.com/azure/ai-foundry/responsible-ai/speech-service/text-to-speech/limited-access)
- Personal voice: [overview](https://learn.microsoft.com/azure/ai-services/speech-service/personal-voice-overview), [create](https://learn.microsoft.com/azure/ai-services/speech-service/personal-voice-create-voice), [use](https://learn.microsoft.com/azure/ai-services/speech-service/personal-voice-how-to-use)
- Professional voice: [set up](https://learn.microsoft.com/azure/ai-services/speech-service/professional-voice-create-project), [consent](https://learn.microsoft.com/azure/ai-services/speech-service/professional-voice-create-consent), [training data](https://learn.microsoft.com/azure/ai-services/speech-service/professional-voice-create-training-set), [train](https://learn.microsoft.com/azure/ai-services/speech-service/professional-voice-train-voice), [deploy](https://learn.microsoft.com/azure/ai-services/speech-service/professional-voice-deploy-endpoint)
