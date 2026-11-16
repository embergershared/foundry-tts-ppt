"""Opt-in checks through desktop PowerPoint on Windows; skipped in CI.

    $env:FOUNDRY_TTS_POWERPOINT_TESTS = "1"          # read the synthetic deck through PowerPoint
    $env:FOUNDRY_TTS_ACCEPTANCE_DECK = "<path>.pptx"  # also read a real (labeled) deck
    .venv\\Scripts\\python -m pytest -q tests/test_powerpoint.py

The acceptance deck stays outside the repository; these tests never print its notes.
"""

import faulthandler
import hashlib
import math
import os
import struct
import sys
import wave
from pathlib import Path

import pytest
from decks import make_deck
from pptx import Presentation

from foundry_tts import deck, markup, notes, powerpoint
from foundry_tts.powerpoint import Narration

SHAPE = "foundry-tts narration"
SAMPLE_RATE = 24000
TONE_HZ = 440
AMPLITUDE = 8000

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


def tone(path: Path, seconds: float) -> Path:
    """A WAV tone PowerPoint can embed, instead of Azure audio."""
    frames = b"".join(
        struct.pack("<h", int(AMPLITUDE * math.sin(2 * math.pi * TONE_HZ * n / SAMPLE_RATE)))
        for n in range(int(seconds * SAMPLE_RATE))
    )
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(SAMPLE_RATE)
        stream.writeframes(frames)
    return path


def slide_xml(path: Path) -> list[str]:
    return [slide._element.xml for slide in Presentation(str(path)).slides]


def media_parts(path: Path) -> list[str]:
    package = Presentation(str(path)).part.package
    return sorted(
        str(part.partname) for part in package.iter_parts() if "/media/" in part.partname
    )


def narrate(source: Path, narrations, out: Path):
    return powerpoint.narrate(source, narrations, out, shape_name=SHAPE, margin_points=20)


@needs_powerpoint
def test_narrated_copy_embeds_audio_that_plays_on_entry(tmp_path):
    source = make_deck(tmp_path / "contoso.pptx")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    one, four = tone(tmp_path / "slide-01.wav", 1.0), tone(tmp_path / "slide-04.wav", 2.0)
    out = tmp_path / "contoso.narrated.pptx"

    placed = narrate(source, [Narration(1, one), Narration(4, four)], out)

    assert [(p.slide, round(p.seconds), p.replaced) for p in placed] == [(1, 1, 0), (4, 2, 0)]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before  # the source is untouched
    xml = slide_xml(out)
    for number in (1, 4):
        assert "audioFile" in xml[number - 1]  # an embedded audio shape
        assert "<p:timing" in xml[number - 1]  # with its play-on-entry timing,
        assert 'nodeType="afterEffect"' in xml[number - 1]  # started on its own,
        assert 'nodeType="clickEffect"' not in xml[number - 1]  # not by a click
        assert f'name="{SHAPE}"' in xml[number - 1]
    assert all("audioFile" not in xml[number - 1] for number in (2, 3, 5))
    assert len([part for part in media_parts(out) if part.endswith(".wav")]) == 2

    # A rerun on the narrated copy replaces the audio instead of adding more.
    again = tmp_path / "again.pptx"
    placed = narrate(out, [Narration(1, tone(tmp_path / "new-01.wav", 3.0))], again)
    assert [(p.slide, round(p.seconds), p.replaced) for p in placed] == [(1, 3, 1)]
    xml = slide_xml(again)
    assert xml[0].count("audioFile") == 1
    assert "audioFile" not in xml[3]  # slide 4 lost its audio: it had none this time
    assert [s.number for s in deck.read_slides(again, deck.POWERPOINT)[0]] == [1, 2, 3, 4, 5]
