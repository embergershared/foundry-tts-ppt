"""Reads a deck through desktop PowerPoint on Windows (COM automation, pywin32).

For decks python-pptx can't open: encrypted by a sensitivity label or a password, or an old
.ppt. As in the PowerShell prototype, the deck is opened read-only and without a window, nothing
is saved, and PowerPoint is quit only if this run started it.
"""

import logging
import sys
from pathlib import Path

from foundry_tts.deck import Slide
from foundry_tts.errors import TtsError

log = logging.getLogger(__name__)

APPLICATION = "PowerPoint.Application"
MSO_TRUE = -1
MSO_FALSE = 0
# PpPlaceholderType.ppPlaceholderBody: the notes text on a notes page.
PP_PLACEHOLDER_BODY = 2


def _com_message(error: Exception) -> str:
    """The most useful text of a pywintypes.com_error."""
    details = getattr(error, "excepinfo", None)
    if details and len(details) > 2 and details[2]:
        return str(details[2]).strip()
    return str(error)


def _notes(slide) -> str:
    placeholders = slide.NotesPage.Shapes.Placeholders
    for index in range(1, placeholders.Count + 1):
        shape = placeholders.Item(index)
        if shape.PlaceholderFormat.Type == PP_PLACEHOLDER_BODY and shape.HasTextFrame == MSO_TRUE:
            # PowerPoint separates paragraphs with CR; python-pptx with LF.
            return str(shape.TextFrame.TextRange.Text).replace("\r", "\n")
    return ""


def read_slides(path: Path) -> list[Slide]:
    if sys.platform != "win32":
        raise TtsError(
            f"{path} has to be read through desktop PowerPoint, which needs Windows. "
            "Save an unencrypted copy as .pptx to read it here."
        )
    try:
        import pythoncom
        import pywintypes
        import win32com.client
    except ImportError as error:
        raise TtsError(
            f"pywin32 is missing, so PowerPoint can't be used ({error}). "
            "Install the locked requirements again."
        ) from error

    pythoncom.CoInitialize()
    try:
        try:
            win32com.client.GetActiveObject(APPLICATION)
            was_running = True
        except pywintypes.com_error:
            was_running = False
        try:
            app = win32com.client.Dispatch(APPLICATION)
        except pywintypes.com_error as error:
            raise TtsError(f"Desktop PowerPoint isn't available: {_com_message(error)}") from error
        try:
            log.info("Opening the deck in PowerPoint, read-only.", extra={"deck": str(path)})
            try:
                deck = app.Presentations.Open(
                    str(path.resolve()), MSO_TRUE, MSO_FALSE, MSO_FALSE
                )  # ReadOnly, Untitled, WithWindow
            except pywintypes.com_error as error:
                raise TtsError(
                    f"PowerPoint could not open {path}: {_com_message(error)}"
                ) from error
            try:
                slides = []
                for number in range(1, deck.Slides.Count + 1):
                    slide = deck.Slides.Item(number)
                    hidden = slide.SlideShowTransition.Hidden == MSO_TRUE
                    slides.append(Slide(number=number, hidden=hidden, notes=_notes(slide)))
                    del slide
                return slides
            except pywintypes.com_error as error:
                raise TtsError(
                    f"PowerPoint could not read {path}: {_com_message(error)}"
                ) from error
            finally:
                deck.Close()
                del deck
        finally:
            if not was_running:
                app.Quit()
            del app
    finally:
        pythoncom.CoUninitialize()
