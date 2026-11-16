# Demo: narrate a customer's deck

What the customer sees: you pick their deck, and a few seconds later it plays back as a
self-running presentation. Each slide is narrated from its speaker notes by a Microsoft Foundry
voice and moves on by itself when its narration ends.

One script does it all: `scripts/Start-Demo.ps1`. It opens a file picker, runs
`foundry-tts deck narrate <deck> --auto-advance`, and starts the narrated copy in Slide Show.
The customer's deck is never changed.

## What you need

| What | Where it's explained |
|---|---|
| Windows with desktop PowerPoint (it embeds the audio and plays the show) | |
| The clone set up: `.venv` with the tool installed | [getting-started.md](getting-started.md), sections 1 and 2 |
| The Foundry resource deployed and `.env` filled | [getting-started.md](getting-started.md), section 3 |
| `az login` with the account that has the *Cognitive Services User* role on the resource | [getting-started.md](getting-started.md), section 3 |
| The deck (.pptx), with speaker notes on the slides to narrate | Ask the customer for it, or use your own |

## The day before

1. **Make the desktop shortcut** (once per PC). PowerShell (workstation), in the clone:

   ```powershell
   Set-Location D:\path\to\foundry-tts-ppt
   $repo = (Get-Location).Path
   $powerPoint = (Get-ItemProperty 'Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\powerpnt.exe').'(default)'
   $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut("$([Environment]::GetFolderPath('Desktop'))\Narrate a deck.lnk")
   $shortcut.TargetPath = (Get-Command pwsh).Source
   $shortcut.Arguments = "-NoProfile -NoExit -File `"$repo\scripts\Start-Demo.ps1`""
   $shortcut.WorkingDirectory = $repo
   $shortcut.IconLocation = "$powerPoint,0"
   $shortcut.Save()
   ```

   `-NoExit` keeps the window open after the run, so you can read an error or the copy's path.
   To always use one voice, add `-VoiceProfile <name>` at the end of `Arguments` (the profiles:
   `.venv\Scripts\foundry-tts --list-profiles`).

2. **Do a full run with the demo deck:** double-click **Narrate a deck**, pick the deck, and
   listen to the whole show.
   - The first run calls Azure once per narrated slide; the reruns reuse that audio. Measured on
     the 5-slide test deck (2 narrated slides, 22.5 s of narration): **21 s** for the first run,
     **5 s** for a rerun. A real 15-slide deck reran in 11 s.
   - So on the day, the deck you rehearsed with comes back in seconds. To show the audio being
     made live, pick a deck that hasn't been run, or change one slide's notes: only that slide
     is made again.
   - A word said wrong (an acronym, a product name): add it to the pronunciation list, see
     [tts-tuning.md](tts-tuning.md), and run it again.

3. **Check the sound** goes where the audience will hear it (the room's speakers, the meeting's
   shared audio).

## During the demo

| Step | You do | The customer sees |
|---|---|---|
| 1 | Double-click **Narrate a deck** | A PowerShell window, then a file picker |
| 2 | Pick the deck | "Azure sign-in OK", then one log line per step (notes cleaned, audio made or reused, narration embedded) |
| 3 | Wait | `Ready to play: …\output\<deck>\<deck>.narrated.pptx`, and the Slide Show starts |
| 4 | Nothing | Each slide's narration plays on its own; the deck moves on when it ends (a click still advances) |
| 5 | Click or press Esc on the black "End of slide show" screen | Back to the desktop |

**Points to make while it plays:**

- The narration comes from the speaker notes the presenter already wrote. Presenter cues are
  cleaned first: `(Click)` becomes a short pause, emoji and quotes are dropped, bullets become
  separate sentences.
- The voice is a Microsoft Foundry text-to-speech voice, called with an Entra ID sign-in. There
  are no keys. The customer would deploy the same resource in their own subscription with `azd`
  (`infra/`).
- The original deck is untouched. The copy has the audio embedded, so it can be shared on its
  own. A deck protected by a sensitivity label stays protected: PowerPoint saves the copy with
  the same label.
- When the notes change, a rerun only makes the changed slides' audio again.
- The same deck can be exported to MP4 (next section).

**Showing a video too.** PowerShell (workstation), in the clone:

```powershell
.venv\Scripts\foundry-tts deck narrate "<path to the deck>.pptx" --video
```

The MP4 goes next to the narrated copy (`output\<deck>\<deck>.narrated.mp4`). Run it before the
demo rather than live: PowerPoint renders the whole show. A video is **not** protected by the
deck's label: anyone who has the file can watch it.

## If something goes wrong

| You see | Do this |
|---|---|
| The window closes at once, or says running scripts is disabled | The PC's execution policy blocks scripts (`Get-ExecutionPolicy -List`). A file from a ZIP download is blocked until `Unblock-File` is run on it; a policy set by your organization is theirs to change |
| "The Azure sign-in has expired or is missing" | `az login`, then double-click the shortcut again |
| `foundry-tts is not installed in …\.venv` | [getting-started.md](getting-started.md), section 2 |
| An error that mentions 401 or 403 | Wrong account or tenant (`az account show`), or the role is missing on the resource |
| "Unknown profile …" | The shortcut's `-VoiceProfile` doesn't match a profile: check `--list-profiles` |
| A slide is silent | It has no notes, only `//` comments, or it is hidden: the log line "Deck read." lists the skipped slides and why |
| The show plays but nothing is heard | The sound output: Windows volume, the room's speakers, or "share sound" in the meeting |
| PowerPoint can't open a labeled deck | Your account must be allowed to open it: open it once in PowerPoint first |
| The file picker doesn't open | Run it with the deck's path: `.\scripts\Start-Demo.ps1 -Deck "<path to the deck>.pptx"` |
| Anything else, with no time to fix it | Open the copy from the rehearsal yourself (`output\<deck>\<deck>.narrated.pptx`) and press F5 |

## Afterwards

- The narrated copy, its audio and `manifest.json` are in `output\<deck name>\`. They hold the
  customer's content: give them the copy if they want it, then delete the folder.
  `output\` is gitignored, so it can't be committed by mistake. Never copy a customer's deck or
  its audio into the repository, an issue or a PR.

  ```powershell
  Remove-Item -Recurse -Force "output\<deck name>"
  ```

- The Foundry resource costs nothing while unused, but you can remove it: see
  [getting-started.md](getting-started.md#remove-the-resources).
