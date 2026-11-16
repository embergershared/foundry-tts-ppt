# 0001: Read sensitivity-labeled decks through desktop PowerPoint

- **Date:** 2026-11-11
- **Status:** accepted
- **Issue:** #11

## Context

Phase 3 reads speaker notes with `python-pptx`. The real sample deck is protected by a
Microsoft Purview sensitivity label: the file is an OLE compound file holding an
`EncryptedPackage`, not the ZIP package `python-pptx` reads, so it fails as a "corrupt file".
Only an application that holds the user's rights to the label, such as desktop PowerPoint, can
decrypt it. Real decks are likely to carry labels. The PowerShell prototype already reads decks
through PowerPoint COM (read-only, no window).

## Options

| Option | For | Against |
|---|---|---|
| A. `python-pptx` for normal decks; labeled ones (an OLE file) read through desktop PowerPoint, COM via `pywin32` | Real, labeled decks work. PowerPoint applies the label's rights, so the tool never handles keys. Same approach as the prototype | Windows + desktop PowerPoint for labeled decks; the PowerPoint path can't run in CI (opt-in tests, a manual check); one more package (`pywin32`, Windows only) |
| B. `python-pptx` only; refuse labeled decks with a clear message | No Office dependency; everything testable in CI | The real deck can't be used until phase 4; users must save an unlabeled copy, which a label may forbid |

## Decision

Option A. The file's first bytes decide: a ZIP is read with `python-pptx`, an OLE file
(a sensitivity label, a password, or an old .ppt) through PowerPoint. `--reader` forces either.
On another OS, an OLE file stops with a message that names the reason.

## Consequences

- CI covers the detection of a labeled file (from its header) and everything after reading; the
  PowerPoint reader is checked by opt-in tests (`tests/test_powerpoint.py`): it must return the
  same notes as `python-pptx` for the synthetic deck, and it reads the local acceptance deck.
- PowerPoint is opened read-only without a window, nothing is saved, and it is quit only if the
  tool started it.
- Phase 4 (writing the narrated deck) has to deal with labels too: `python-pptx` can't write an
  encrypted deck either, which weighs toward PowerPoint COM there as well. Whether a copy saved by
  PowerPoint keeps the label is still to check.
