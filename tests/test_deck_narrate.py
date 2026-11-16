import json
import logging
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
from conftest import CONFIG, fake_token
from decks import make_deck
from fake_powerpoint import FakePresentation

from foundry_tts import cli, deck, deck_narrate, powerpoint
from foundry_tts.errors import TtsError
from foundry_tts.powerpoint import MSO_FALSE, MSO_TRUE, Narration

NOW = datetime(2026, 11, 12, 9, 0, 0)
SHAPE = "foundry-tts narration"


def audio(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(b"audio")
    return path


def place(presentation, narrations):
    return powerpoint.place_narrations(
        presentation, narrations, shape_name=SHAPE, margin_points=20
    )


# ---- place_narrations, on a fake PowerPoint ----


def test_audio_is_embedded_off_the_slide_playing_on_entry_and_hidden(tmp_path):
    one, three = audio(tmp_path, "slide-01.mp3"), audio(tmp_path, "slide-03.mp3")
    presentation = FakePresentation(3, {str(one.resolve()): 12_340, str(three.resolve()): 5_000})

    placed = place(presentation, [Narration(1, one), Narration(3, three)])

    assert placed == [powerpoint.Placed(1, 12.34, 0), powerpoint.Placed(3, 5.0, 0)]
    (shape,) = presentation.slide(1).Shapes.items
    assert shape.media_path == str(one.resolve())
    assert (shape.link_to_file, shape.save_with_document) == (MSO_FALSE, MSO_TRUE)
    assert (shape.Left, shape.Top) == (960.0 + 20, 0)  # just right of the slide
    assert shape.Name == SHAPE
    assert shape.Tags.Item(powerpoint.TAG_NAME) == powerpoint.TAG_NARRATION
    play = shape.AnimationSettings.PlaySettings
    assert (play.PlayOnEntry, play.HideWhileNotPlaying) == (MSO_TRUE, MSO_TRUE)
    assert presentation.slide(2).Shapes.items == []


def test_narration_starts_on_its_own_before_the_slides_click_animations(tmp_path):
    one = audio(tmp_path, "slide-01.mp3")
    presentation = FakePresentation(1, {str(one.resolve()): 1_000})
    slide = presentation.slide(1)
    title = slide.Shapes.add("Title")
    slide.TimeLine.MainSequence.add(title, effect_type=10)  # a click animation of the slide's own

    place(presentation, [Narration(1, one)])

    first, second = slide.TimeLine.MainSequence.items
    assert first.Shape.Name == SHAPE and first.EffectType == powerpoint.MSO_ANIM_EFFECT_MEDIA_PLAY
    assert first.Timing.TriggerType == powerpoint.MSO_ANIM_TRIGGER_AFTER_PREVIOUS
    assert first.Timing.TriggerDelayTime == 0
    assert second.Shape is title and second.Timing.TriggerType == 1  # untouched


def test_a_missing_play_effect_is_refused(tmp_path, monkeypatch):
    one = audio(tmp_path, "slide-01.mp3")
    presentation = FakePresentation(1, {str(one.resolve()): 1_000})
    shapes = presentation.slide(1).Shapes
    add = shapes.AddMediaObject2

    def add_without_effect(*args):
        shape = add(*args)
        shape.AnimationSettings.PlaySettings.adds_effect = False
        return shape

    monkeypatch.setattr(shapes, "AddMediaObject2", add_without_effect)
    with pytest.raises(TtsError, match="no play effect"):
        place(presentation, [Narration(1, one)])


def test_a_rerun_replaces_earlier_narration_and_keeps_other_media(tmp_path):
    new = audio(tmp_path, "slide-01.mp3")
    presentation = FakePresentation(2, {str(new.resolve()): 1_000})
    slide_1, slide_2 = presentation.slide(1), presentation.slide(2)
    slide_1.Shapes.add(SHAPE)  # found by name
    renamed = slide_1.Shapes.add("Audio the user renamed")  # found by tag
    renamed.Tags.Add(powerpoint.TAG_NAME, powerpoint.TAG_NARRATION)
    music = slide_1.Shapes.add("Background music")
    slide_2.Shapes.add(SHAPE)  # slide 2 has no audio any more

    placed = place(presentation, [Narration(1, new)])

    assert placed == [powerpoint.Placed(1, 1.0, 2)]
    assert [s.Name for s in slide_1.Shapes.items] == ["Background music", SHAPE]
    assert slide_1.Shapes.items[0] is music
    assert slide_2.Shapes.items == []


def test_audio_for_a_slide_the_deck_lacks_is_refused(tmp_path):
    with pytest.raises(
        TtsError, match=r"The deck has 2 slides; there is audio for slide\(s\) \[5\]"
    ):
        place(FakePresentation(2), [Narration(5, audio(tmp_path, "slide-05.mp3"))])


def test_audio_powerpoint_cant_measure_is_refused(tmp_path):
    with pytest.raises(TtsError, match="no length"):
        place(FakePresentation(1), [Narration(1, audio(tmp_path, "slide-01.mp3"))])


# ---- deck narrate, with PowerPoint replaced ----


@pytest.fixture
def local(settings, tmp_path):
    return replace(settings, output_folder=tmp_path / "output")


@pytest.fixture
def contoso(tmp_path):
    return make_deck(tmp_path / "contoso.pptx")


@pytest.fixture
def fake_narrate(monkeypatch):
    """Records the calls to powerpoint.narrate and writes a stand-in narrated deck."""
    calls = []

    def narrate(path, narrations, out_path, *, shape_name, margin_points):
        calls.append(
            {"path": path, "narrations": narrations, "out": out_path, "shape": shape_name}
        )
        out_path.write_bytes(b"PK\x03\x04narrated")
        return [powerpoint.Placed(n.slide, 1.5, 0) for n in narrations]

    monkeypatch.setattr(powerpoint, "narrate", narrate)
    return calls


def run(argv, settings, client):
    args = cli.build_deck_parser().parse_args(argv)
    return cli.run_deck(args, settings, client=client, get_token=fake_token, now=NOW)


def test_narrate_makes_the_audio_then_the_narrated_copy(
    local, client, transport, contoso, fake_narrate, tmp_path
):
    out = run(["narrate", str(contoso)], local, client)

    folder = tmp_path / "output" / "contoso"
    assert out == folder / "contoso.narrated.pptx"
    assert len(transport.requests) == 2  # slides 1 and 4 have notes
    (call,) = fake_narrate
    assert call["path"] == contoso
    assert call["shape"] == SHAPE
    assert call["narrations"] == [
        Narration(1, folder / "slide-01.mp3"),
        Narration(4, folder / "slide-04.mp3"),
    ]


def test_skip_synth_reuses_the_manifest_without_azure(
    local, client, transport, contoso, fake_narrate, tmp_path
):
    run(["synth", str(contoso)], local, client)
    transport.requests.clear()
    deck_out = tmp_path / "share" / "contoso narrated.pptx"
    out = run(
        ["narrate", str(contoso), "--skip-synth", "--deck-out", str(deck_out)], local, client
    )
    assert out == deck_out and deck_out.exists()
    assert transport.requests == []


@pytest.mark.parametrize(
    ("prepare", "argv", "message"),
    [
        (None, ["--skip-synth"], "No manifest"),
        ("wrong-deck", ["--skip-synth"], "is for other.pptx, not contoso.pptx"),
        ("missing-audio", ["--skip-synth"], "slide-04.mp3 is missing"),
        ("old-version", ["--skip-synth"], "manifest version 0"),
        ("existing-out", [], "already exists"),
    ],
)
def test_narrate_problems_stop_before_powerpoint(
    local, client, contoso, fake_narrate, tmp_path, prepare, argv, message
):
    folder = tmp_path / "output" / "contoso"
    if prepare is not None:
        run(["synth", str(contoso)], local, client)
        manifest_path = folder / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if prepare == "wrong-deck":
            manifest["deck"] = "other.pptx"
        elif prepare == "missing-audio":
            (folder / "slide-04.mp3").unlink()
        elif prepare == "old-version":
            manifest["version"] = 0
        elif prepare == "existing-out":
            (folder / "contoso.narrated.pptx").write_bytes(b"old")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(TtsError, match=message):
        run(["narrate", str(contoso), *argv], local, client)
    assert fake_narrate == []


@pytest.mark.parametrize(
    ("deck_out", "message"),
    [("contoso.pptx", "can't replace the source deck"), ("copy.ppt", "saved as .pptx")],
)
def test_narrated_copy_path_is_checked(local, client, contoso, fake_narrate, deck_out, message):
    with pytest.raises(TtsError, match=message):
        run(["narrate", str(contoso), "--deck-out", str(contoso.parent / deck_out)], local, client)


def test_overwrite_replaces_an_earlier_narrated_copy(
    local, client, contoso, fake_narrate, tmp_path
):
    run(["narrate", str(contoso)], local, client)
    out = run(["narrate", str(contoso), "--overwrite"], local, client)
    assert out.read_bytes() == b"PK\x03\x04narrated"
    assert len(fake_narrate) == 2


def test_an_encrypted_source_with_an_unencrypted_copy_is_flagged(
    local, client, contoso, fake_narrate, monkeypatch, caplog
):
    run(["synth", str(contoso)], local, client)
    real_kind = deck.file_kind
    # The source looks encrypted; the stand-in narrated copy is a plain ZIP.
    monkeypatch.setattr(
        deck_narrate.deck,
        "file_kind",
        lambda path: deck.OLE if path == contoso else real_kind(path),
    )
    with caplog.at_level(logging.WARNING):
        run(["narrate", str(contoso), "--skip-synth"], local, client)
    assert "check its label in PowerPoint" in caplog.text


def test_main_narrate_reports_errors(tmp_path, monkeypatch, caplog):
    monkeypatch.chdir(tmp_path)
    with caplog.at_level(logging.ERROR):
        code = cli.main(
            ["deck", "narrate", str(tmp_path / "missing.pptx"), "--config", str(CONFIG)]
        )
    assert code == 1
    assert "Deck not found" in caplog.text
