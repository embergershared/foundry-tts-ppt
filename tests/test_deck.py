import sys

import pytest
from decks import SLIDE_1_NOTES, SLIDE_4_NOTES, make_deck

from foundry_tts import deck, powerpoint
from foundry_tts.errors import TtsError

OLE_HEADER = bytes.fromhex("D0CF11E0A1B11AE1")


@pytest.fixture
def contoso(tmp_path):
    return make_deck(tmp_path / "contoso.pptx")


@pytest.fixture
def labeled(tmp_path):
    """Stands in for a deck encrypted by a sensitivity label: an OLE file, not a ZIP."""
    path = tmp_path / "labeled.pptx"
    path.write_bytes(OLE_HEADER + b"\x00" * 504)
    return path


def test_python_pptx_reads_numbers_hidden_slides_and_notes(contoso):
    slides, reader = deck.read_slides(contoso)
    assert reader == deck.PYTHON_PPTX
    assert [(s.number, s.hidden) for s in slides] == [
        (1, False),
        (2, False),
        (3, True),
        (4, False),
        (5, False),
    ]
    # Paragraphs come back separated by \n and line breaks as \v, like PowerPoint's CR and \v.
    assert slides[0].notes == SLIDE_1_NOTES
    assert slides[1].notes == ""
    assert slides[3].notes == SLIDE_4_NOTES


def test_file_kind_from_the_first_bytes(contoso, labeled, tmp_path):
    assert deck.file_kind(contoso) == deck.ZIP
    assert deck.file_kind(labeled) == deck.OLE
    text = tmp_path / "notes.txt"
    text.write_text("not a deck", encoding="utf-8")
    with pytest.raises(TtsError, match="is not a PowerPoint file"):
        deck.file_kind(text)
    with pytest.raises(TtsError, match="Deck not found"):
        deck.file_kind(tmp_path / "missing.pptx")


def test_labeled_deck_is_refused_by_python_pptx_with_the_reason(labeled):
    with pytest.raises(TtsError, match="sensitivity label or a password"):
        deck.read_slides(labeled, deck.PYTHON_PPTX)


def test_labeled_deck_goes_to_powerpoint_on_auto(labeled, monkeypatch):
    seen = []

    def fake_read(path):
        seen.append(path)
        return [deck.Slide(1, False, "Hello")]

    monkeypatch.setattr(powerpoint, "read_slides", fake_read)
    slides, reader = deck.read_slides(labeled)
    assert (reader, seen, slides[0].notes) == (deck.POWERPOINT, [labeled], "Hello")


def test_powerpoint_can_be_asked_for_a_normal_deck(contoso, monkeypatch):
    monkeypatch.setattr(powerpoint, "read_slides", lambda path: [])
    assert deck.read_slides(contoso, deck.POWERPOINT) == ([], deck.POWERPOINT)


def test_powerpoint_needs_windows(labeled, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(TtsError, match="needs Windows"):
        powerpoint.read_slides(labeled)


def test_a_broken_pptx_fails_loudly(tmp_path):
    broken = tmp_path / "broken.pptx"
    broken.write_bytes(b"PK\x03\x04" + b"\x00" * 100)
    with pytest.raises(TtsError, match="could not be read as a .pptx"):
        deck.read_slides(broken)


def test_unknown_reader_is_refused(contoso):
    with pytest.raises(TtsError, match="Unknown reader"):
        deck.read_slides(contoso, "libreoffice")
