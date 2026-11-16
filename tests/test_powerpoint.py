"""Opt-in checks through desktop PowerPoint on Windows; skipped in CI.

    $env:FOUNDRY_TTS_POWERPOINT_TESTS = "1"          # read the synthetic deck through PowerPoint
    $env:FOUNDRY_TTS_ACCEPTANCE_DECK = "<path>.pptx"  # also read a real (labeled) deck
    .venv\\Scripts\\python -m pytest -q tests/test_powerpoint.py

The acceptance deck stays outside the repository; these tests never print its notes.
"""

import faulthandler
import os
import sys
from pathlib import Path

import pytest
from decks import make_deck

from foundry_tts import deck, markup, notes

WINDOWS = sys.platform == "win32"
ENABLED = os.environ.get("FOUNDRY_TTS_POWERPOINT_TESTS") == "1"
ACCEPTANCE_DECK = os.environ.get("FOUNDRY_TTS_ACCEPTANCE_DECK")

needs_powerpoint = pytest.mark.skipif(
    not (WINDOWS and ENABLED), reason="set FOUNDRY_TTS_POWERPOINT_TESTS=1 on Windows"
)


@pytest.fixture(autouse=True)
def quiet_fault_handler():
    """Releasing PowerPoint after Quit raises RPC_E_DISCONNECTED (0x80010108) inside COM, which
    COM handles; pytest's fault handler would still print it as a "fatal exception"."""
    was_enabled = faulthandler.is_enabled()
    faulthandler.disable()
    yield
    if was_enabled:
        faulthandler.enable()


@needs_powerpoint
def test_powerpoint_reads_the_same_notes_as_python_pptx(tmp_path):
    path = make_deck(tmp_path / "contoso.pptx")
    by_python_pptx, _ = deck.read_slides(path, deck.PYTHON_PPTX)
    by_powerpoint, reader = deck.read_slides(path, deck.POWERPOINT)
    assert reader == deck.POWERPOINT
    assert by_powerpoint == by_python_pptx


@needs_powerpoint
@pytest.mark.skipif(not ACCEPTANCE_DECK, reason="set FOUNDRY_TTS_ACCEPTANCE_DECK")
def test_acceptance_deck_is_read(caplog):
    path = Path(ACCEPTANCE_DECK)
    slides, reader = deck.read_slides(path)
    if deck.file_kind(path) == deck.OLE:
        assert reader == deck.POWERPOINT
    assert slides, "the deck has no slides"
    with_notes = [slide for slide in slides if slide.notes.strip()]
    assert with_notes, "no slide has notes"
    for slide in with_notes:
        cleaned = notes.clean(slide.notes, cue_pause_ms=500)
        markup.parse(cleaned.text, allow_empty=True)  # raises on bad markup
