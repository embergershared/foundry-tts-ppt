# 0002: Write the narrated deck through desktop PowerPoint

- **Date:** 2026-11-12
- **Status:** accepted
- **Issue:** #12

## Context

Phase 4 embeds each slide's audio in a copy of the deck, set to play on its own in Slide Show.
`python-pptx` has no audio API: the tool would have to write the media part, the audio shape,
its relationships and the slide's `<p:timing>` itself. Real decks may carry a sensitivity label
([0001](0001-read-labeled-decks-through-powerpoint.md)), which encrypts the file: `python-pptx`
can neither read nor write it. The PowerShell prototype already embeds audio through PowerPoint.

## Options

| Option | For | Against |
|---|---|---|
| A. Open XML with `python-pptx` | Any OS, no Office, testable in CI | Labeled decks impossible (they would still need PowerPoint); the media XML is written by hand and only PowerPoint can say whether it is right |
| B. PowerPoint automation (COM, `pywin32`) | PowerPoint writes its own media parts and timing; labeled decks keep their protection; the same approach as the reader and the prototype | Windows + desktop PowerPoint only; the real path runs only in opt-in tests and by hand |

## Decision

Option B, chosen by the owner at the start of phase 4. The CI tests run the COM steps against a
small fake of PowerPoint's object model (`tests/fake_powerpoint.py`); an opt-in test drives real
PowerPoint and checks the saved package.

## Consequences

- `deck narrate` needs Windows and desktop PowerPoint; `deck synth` does not.
- Measured while building it: `PlayOnEntry` alone makes PowerPoint start the audio **on click**.
  The tool moves the play effect first and sets it to start after the slide appears; the opt-in
  test checks the saved XML (`afterEffect`, no `clickEffect`).
- A narrated copy of a real labeled deck was saved by PowerPoint and kept its encryption.
- Phase 5 (slide timings, video export) uses the same PowerPoint session.
