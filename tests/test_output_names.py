import logging
from dataclasses import replace
from pathlib import Path

import pytest

from foundry_tts import output_names
from foundry_tts.errors import TtsError
from foundry_tts.output_names import NARRATED_SUFFIX, path_chars

LONG = "Northwind review - final with transitions"
# LONG one character shorter, cut back to the last whole word.
LONG_CUT = "Northwind review - final with"
DECK = Path(f"{LONG}.pptx")


def limits(settings, max_path_chars, min_name_chars=20):
    return replace(settings.deck, max_path_chars=max_path_chars, min_name_chars=min_name_chars)


def test_repository_limits_are_powerpoints(settings):
    assert (settings.deck.max_path_chars, settings.deck.min_name_chars) == (259, 20)


def test_a_name_that_fits_is_kept(settings, tmp_path):
    fits = path_chars(tmp_path) + 1 + len(LONG) + len(NARRATED_SUFFIX)
    out = output_names.output_file(DECK, tmp_path, NARRATED_SUFFIX, limits(settings, fits))
    assert out == tmp_path / f"{LONG}{NARRATED_SUFFIX}"


def test_one_character_over_cuts_the_name_at_a_word(settings, tmp_path, caplog):
    """Issue #25: one character over the limit, PowerPoint saved the copy under a cut name."""
    limit = path_chars(tmp_path) + 1 + len(LONG) + len(NARRATED_SUFFIX) - 1
    with caplog.at_level(logging.INFO):
        out = output_names.output_file(DECK, tmp_path, NARRATED_SUFFIX, limits(settings, limit))
    assert out == tmp_path / f"{LONG_CUT}{NARRATED_SUFFIX}"
    assert path_chars(out) <= limit
    assert "shortened to stay within PowerPoint's path limit" in caplog.text


@pytest.mark.parametrize(
    ("name", "room", "expected"),
    [
        ("x" * 50, 30, "x" * 30),  # no space: cut where the room ends
        ("Northwind-2027-final-version", 21, "Northwind-2027-final"),  # no dangling "-"
        ("Northwind review 2027 - final", 25, "Northwind review 2027"),  # at a word, no " -"
        ("Northwind reviewing2027final", 25, "Northwind reviewing2027fi"),  # a word cut: < 20
    ],
)
def test_shortened_names(settings, tmp_path, name, room, expected):
    limit = path_chars(tmp_path) + 1 + room + len(NARRATED_SUFFIX)
    out = output_names.output_file(
        Path(f"{name}.pptx"), tmp_path, NARRATED_SUFFIX, limits(settings, limit, min_name_chars=20)
    )
    assert out.name == f"{expected}{NARRATED_SUFFIX}"


@pytest.mark.parametrize(
    ("file_name", "expected"),
    [
        ("Contoso review .pptx", "Contoso review"),  # issue #39: a space before .pptx
        ("Contoso review. .pptx", "Contoso review"),  # dots and spaces
        ("Contoso review..pptx", "Contoso review"),
        ("Contoso - review_.pptx", "Contoso - review_"),  # only what Windows drops
        (" Contoso review.pptx", " Contoso review"),  # a leading space is kept by Windows
        (". .pptx", "deck"),  # nothing left: a usable name
        ("CON.pptx", "CON_"),  # reserved device names
        ("nul .pptx", "nul_"),
        ("com1.pptx", "com1_"),
        ("LPT9.pptx", "LPT9_"),
        ("CONTOSO.pptx", "CONTOSO"),  # only the whole name is reserved
        ("COM10.pptx", "COM10"),
    ],
)
def test_deck_names_drop_what_windows_drops(file_name, expected):
    assert output_names.deck_name(Path(file_name)) == expected


# Names real decks have: each must give a folder and files that can be written and found again.
HOSTILE_NAMES = [
    "Contoso review .pptx",
    "Contoso review..pptx",
    "Contoso review . .pptx",
    "Contoso – 2027 Overview — Final.pptx",  # en and em dashes
    "Présentation équipe Fabrikam.pptx",
    "Contoso [draft] (v2) {final}.pptx",
    "Contoso's review & Q&A #1 100%.pptx",
    "Contoso  two  spaces.pptx",
    " Contoso leading space.pptx",
    "Contoso 🚀 launch.pptx",
    "Contoso;review,v1=final+edits~.pptx",
    "con.pptx",
]


@pytest.mark.parametrize("file_name", HOSTILE_NAMES)
def test_real_world_deck_names_give_writable_paths(settings, tmp_path, file_name):
    deck = Path(file_name)
    local = replace(settings, output_folder=tmp_path)
    folder = output_names.default_folder(deck, local)
    out = output_names.output_file(deck, folder, NARRATED_SUFFIX, settings.deck)
    folder.mkdir()
    (folder / "slide-01.mp3").write_bytes(b"x")
    out.write_bytes(b"x")
    # What Windows made is what the paths name: the same folder, found again by a rerun.
    assert [p.name for p in tmp_path.iterdir()] == [folder.name]
    assert sorted(p.name for p in folder.iterdir()) == sorted([out.name, "slide-01.mp3"])
    assert output_names.default_folder(deck, local) == folder


def test_a_deck_name_ending_with_a_space_gives_paths_windows_can_write(settings, tmp_path):
    """Issue #39: output/<name >/ was created as output/<name>/, then every write in it failed."""
    deck = Path("Contoso review .pptx")
    local = replace(settings, output_folder=tmp_path)
    folder = output_names.default_folder(deck, local)
    out = output_names.output_file(deck, folder, NARRATED_SUFFIX, settings.deck)
    assert folder == tmp_path / "Contoso review"
    assert out == folder / f"Contoso review{NARRATED_SUFFIX}"
    folder.mkdir()
    out.write_bytes(b"x")  # the folder Windows made is the one the path names
    assert out.read_bytes() == b"x"


def test_a_folder_without_room_for_a_name_is_refused(settings, tmp_path):
    just_enough = path_chars(tmp_path) + 1 + 20 + len(NARRATED_SUFFIX)
    output_names.check_folder(tmp_path, limits(settings, just_enough))
    too_tight = limits(settings, just_enough - 1)
    with pytest.raises(TtsError, match="too long for PowerPoint.*min_name_chars"):
        output_names.check_folder(tmp_path, too_tight)
    with pytest.raises(TtsError, match="too long for PowerPoint"):
        output_names.output_file(DECK, tmp_path, NARRATED_SUFFIX, too_tight)


def test_the_default_folder_keeps_the_deck_name_unless_it_leaves_no_room(settings, tmp_path):
    root = tmp_path / "output"
    local = replace(settings, output_folder=root)
    needed = path_chars(root) + 1 + len(LONG) + 1 + 20 + len(NARRATED_SUFFIX)

    def folder(max_path_chars):
        return output_names.default_folder(
            DECK, replace(local, deck=limits(settings, max_path_chars))
        )

    kept, shortened = folder(needed), folder(needed - 1)

    assert kept == root / LONG
    assert shortened == root / LONG_CUT


def test_an_explicit_path_that_doesnt_fit_is_refused(settings, tmp_path):
    path = tmp_path / "copy.pptx"
    output_names.check_fits(path, "--deck-out", limits(settings, path_chars(path)))
    with pytest.raises(TtsError, match="can't save a path longer than .*shorter --deck-out"):
        output_names.check_fits(path, "--deck-out", limits(settings, path_chars(path) - 1))
