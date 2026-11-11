"""Reads the slides of a deck: their number, whether they are hidden, and their speaker notes.

Two readers:

- `python-pptx`: any OS, no Office needed. Reads a normal .pptx (a ZIP package).
- `powerpoint`: desktop PowerPoint on Windows, through COM (powerpoint.py). Needed for a deck
  that is an OLE file instead of a ZIP: one encrypted by a sensitivity label or a password, or an
  old .ppt. PowerPoint opens it with the signed-in user's rights.

`auto` picks python-pptx for a ZIP and PowerPoint for an OLE file, from the file's first bytes.
"""

import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path

from foundry_tts.errors import TtsError

log = logging.getLogger(__name__)

AUTO = "auto"
PYTHON_PPTX = "python-pptx"
POWERPOINT = "powerpoint"
READERS = (AUTO, PYTHON_PPTX, POWERPOINT)

ZIP = "zip"
OLE = "ole"
_ZIP_SIGNATURE = b"PK\x03\x04"
# Compound File Binary (OLE) signature: encrypted Office files and old .ppt files.
_OLE_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")
# <p:sld show="0">: the slide is hidden in Slide Show (ST_Boolean: 0/false).
_HIDDEN_VALUES = ("0", "false")

ENCRYPTED_HINT = (
    "It is an encrypted file (a sensitivity label or a password) or an old .ppt, which "
    "python-pptx can't open."
)


@dataclass(frozen=True)
class Slide:
    number: int
    hidden: bool
    # Paragraphs separated by \n, line breaks inside a paragraph as \v; "" without notes.
    notes: str


def file_kind(path: Path) -> str:
    """ZIP (a normal .pptx) or OLE (encrypted, or an old .ppt), from the first bytes."""
    try:
        with path.open("rb") as stream:
            head = stream.read(len(_OLE_SIGNATURE))
    except FileNotFoundError:
        raise TtsError(f"Deck not found: {path}") from None
    if head.startswith(_ZIP_SIGNATURE):
        return ZIP
    if head == _OLE_SIGNATURE:
        return OLE
    raise TtsError(f"{path} is not a PowerPoint file.")


def read_slides(path: Path, reader: str = AUTO) -> tuple[list[Slide], str]:
    """The slides of the deck, and the reader that read them."""
    if reader not in READERS:
        raise TtsError(f"Unknown reader '{reader}': use one of {', '.join(READERS)}.")
    kind = file_kind(path)
    if reader == AUTO:
        reader = PYTHON_PPTX if kind == ZIP else POWERPOINT
        if kind == OLE:
            log.info(
                "The deck is encrypted or an old .ppt: reading it through PowerPoint.",
                extra={"deck": str(path)},
            )
    if reader == PYTHON_PPTX and kind == OLE:
        raise TtsError(f"{path}: {ENCRYPTED_HINT} Use --reader powerpoint (Windows).")
    if reader == POWERPOINT:
        from foundry_tts import powerpoint

        return powerpoint.read_slides(path), reader
    return _read_with_python_pptx(path), reader


def _read_with_python_pptx(path: Path) -> list[Slide]:
    from pptx import Presentation
    from pptx.exc import PackageNotFoundError

    try:
        presentation = Presentation(str(path))
    except (PackageNotFoundError, KeyError, zipfile.BadZipFile) as error:
        raise TtsError(f"{path} could not be read as a .pptx: {error}") from error
    slides = []
    for number, slide in enumerate(presentation.slides, start=1):
        notes = ""
        if slide.has_notes_slide:
            frame = slide.notes_slide.notes_text_frame
            if frame is not None:
                notes = frame.text
        hidden = slide._element.get("show") in _HIDDEN_VALUES  # no public API for it
        slides.append(Slide(number=number, hidden=hidden, notes=notes))
    return slides
