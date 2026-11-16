import hashlib
import json
import logging
from dataclasses import replace
from datetime import datetime

import httpx
import pytest
from conftest import CONFIG, FAKE_AUDIO, RecordingTransport, fake_token
from decks import make_deck

from foundry_tts import cli
from foundry_tts.errors import TtsError

NOW = datetime(2026, 11, 11, 15, 0, 0)


@pytest.fixture
def local(settings, tmp_path):
    return replace(settings, output_folder=tmp_path / "output")


@pytest.fixture
def contoso(tmp_path):
    return make_deck(tmp_path / "contoso.pptx")


@pytest.fixture
def words(tmp_path):
    path = tmp_path / "words.toml"
    path.write_text(
        '[lexicon]\n"R&D" = "R and D"\n"Q&A" = "Q and A"\n'
        '"cloud@contoso.com" = "cloud at contoso dot com"\n',
        encoding="utf-8",
    )
    return path


def synth(argv, settings, client):
    args = cli.build_deck_parser().parse_args(["synth", *argv])
    return cli.run_deck(args, settings, client=client, get_token=fake_token, now=NOW)


def read_manifest(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_one_audio_file_per_slide_with_notes_and_a_manifest(
    local, client, transport, contoso, words, tmp_path
):
    manifest_path = synth([str(contoso), "--lexicon", str(words)], local, client)

    folder = tmp_path / "output" / "contoso"
    assert manifest_path == folder / "manifest.json"
    assert sorted(p.name for p in folder.iterdir()) == [
        "manifest.json",
        "slide-01.mp3",
        "slide-04.mp3",
    ]
    assert (folder / "slide-01.mp3").read_bytes() == FAKE_AUDIO

    manifest = read_manifest(manifest_path)
    assert {key: manifest[key] for key in ("version", "deck", "reader", "created")} == {
        "version": 1,
        "deck": "contoso.pptx",
        "reader": "python-pptx",
        "created": "2026-11-11T15:00:00",
    }
    assert (manifest["profile"], manifest["engine"], manifest["voice"]) == (
        "ava-hd",
        "speech",
        "en-US-Ava:DragonHDLatestNeural",
    )
    assert manifest["slide_count"] == 5
    assert [(s["slide"], s["file"], s["requests"]) for s in manifest["slides"]] == [
        (1, "slide-01.mp3", 1),
        (4, "slide-04.mp3", 1),
    ]
    assert manifest["skipped"] == [
        {"slide": 2, "reason": "no notes"},
        {"slide": 3, "reason": "hidden"},
        {"slide": 5, "reason": "no notes"},  # only a comment
    ]
    # The hash is the sha256 of the audio format and exactly what was sent.
    for entry, request in zip(manifest["slides"], transport.requests, strict=True):
        sent = local.speech.output_format.encode() + b"\n" + request.content
        assert entry["hash"] == "sha256:" + hashlib.sha256(sent).hexdigest()
    assert manifest["slides"][0]["cleanups"] == {
        "cue": 1,
        "emoji": 1,
        "bullet": 3,
        "space": 1,
    }
    assert manifest["slides"][1]["cleanups"] == {"cue": 1, "quote": 4, "range": 1}


def test_the_ssml_sent_has_the_cleanups_markup_and_lexicon(
    local, client, transport, contoso, words
):
    synth([str(contoso), "--lexicon", str(words)], local, client)
    slide_1, slide_4 = (request.content.decode() for request in transport.requests)

    assert "(Click)" not in slide_1 and "- " not in slide_1
    # The cue is a pause before "Today"; each bullet is its own paragraph.
    assert (
        '<break time="500ms"/> Today we cover three topics: <break time="400ms"/> '
        'the release plan <break time="400ms"/> the '
    ) in slide_1
    assert (
        '<sub alias="A K S">AKS</sub> platform and <sub alias="R and D">R&amp;D</sub>' in slide_1
    )
    assert '<sub alias="Q and A">Q&amp;A</sub> at the end.' in slide_1
    assert chr(0x1F44B) not in slide_1

    assert "Fabrikam" not in slide_4  # the comment line
    assert "November 10 to 15." in slide_4
    assert '<sub alias="cloud at contoso dot com">cloud@contoso.com</sub>' in slide_4
    assert "Zero downtime is the goal." in slide_4
    assert '<break time="500ms"/> Thank you.' in slide_4
    assert '"Thank' not in slide_4 and chr(0x201C) not in slide_4


def test_hidden_slides_on_request(local, client, contoso, tmp_path):
    manifest = read_manifest(synth([str(contoso), "--include-hidden"], local, client))
    assert [s["slide"] for s in manifest["slides"]] == [1, 3, 4]
    assert manifest["slides"][1]["hidden"] is True


def test_openai_profile_and_out_folder(local, client, transport, contoso, tmp_path):
    out = tmp_path / "narration"
    manifest = read_manifest(
        synth([str(contoso), "--profile", "marin-presenter", "--out", str(out)], local, client)
    )
    assert manifest["engine"] == "openai"
    assert (out / "slide-04.mp3").exists()
    body = json.loads(transport.requests[0].content)
    assert body["input"].startswith("Welcome to the Contoso cloud roadmap for 2027.\n\n... Today")


def test_long_notes_are_split_and_joined(local, client, transport, tmp_path):
    long_notes = "\n".join(f"Paragraph {n} has a few words in it." for n in range(1, 9))
    deck_path = make_deck(tmp_path / "long.pptx", [("Long", long_notes, False)])
    small = replace(local, speech=replace(local.speech, max_chars_per_request=100))
    manifest = read_manifest(synth([str(deck_path)], small, client))
    assert manifest["slides"][0]["requests"] == len(transport.requests) == 4
    audio = (tmp_path / "output" / "long" / "slide-01.mp3").read_bytes()
    assert audio == FAKE_AUDIO * 4


def test_save_ssml_writes_one_file_per_request(local, client, contoso, tmp_path):
    synth([str(contoso), "--save-ssml"], local, client)
    folder = tmp_path / "output" / "contoso"
    assert (folder / "slide-01.ssml").read_text(encoding="utf-8").startswith("<speak")


def test_slide_numbers_widen_past_99_slides(local, client, tmp_path):
    slides = [(f"S{n}", "Hi." if n == 100 else None, False) for n in range(1, 101)]
    manifest = read_manifest(synth([str(make_deck(tmp_path / "big.pptx", slides))], local, client))
    assert manifest["slides"][0]["file"] == "slide-100.mp3"


def test_existing_output_stops_the_run_before_any_call(
    local, client, transport, contoso, tmp_path
):
    folder = tmp_path / "output" / "contoso"
    folder.mkdir(parents=True)
    (folder / "slide-04.mp3").write_bytes(b"old")
    with pytest.raises(TtsError, match="already exists"):
        synth([str(contoso)], local, client)
    assert transport.requests == []
    synth([str(contoso), "--overwrite"], local, client)
    assert (folder / "slide-04.mp3").read_bytes() == FAKE_AUDIO


def test_a_deck_without_notes_is_refused(local, client, transport, tmp_path):
    deck_path = make_deck(tmp_path / "silent.pptx", [("A", None, False), ("B", "// x", False)])
    with pytest.raises(TtsError, match="No slide of .* has speaker notes"):
        synth([str(deck_path)], local, client)
    assert transport.requests == []


def test_a_failure_names_the_slide_and_writes_no_manifest(local, contoso, tmp_path):
    with (
        httpx.Client(transport=RecordingTransport(429, b"Too many requests")) as client,
        pytest.raises(TtsError, match="Slide 1: .*HTTP 429.*no manifest was written"),
    ):
        synth([str(contoso)], local, client)
    assert not (tmp_path / "output" / "contoso" / "manifest.json").exists()


def test_a_bad_slide_is_found_before_any_call(local, client, transport, tmp_path):
    deck_path = make_deck(
        tmp_path / "bad.pptx", [("A", "Fine.", False), ("B", "[pause 30s]x", False)]
    )
    with pytest.raises(TtsError, match="too long"):
        synth([str(deck_path)], local, client)
    assert transport.requests == []


def test_main_runs_the_deck_command(tmp_path, monkeypatch, caplog):
    monkeypatch.chdir(tmp_path)
    with caplog.at_level(logging.ERROR):
        code = cli.main(["deck", "synth", str(tmp_path / "missing.pptx"), "--config", str(CONFIG)])
    assert code == 1
    assert "Deck not found" in caplog.text


def test_deck_options_are_parsed():
    args = cli.build_deck_parser().parse_args(
        ["synth", "d.pptx", "--profile", "ava-hd", "--reader", "powerpoint", "--include-hidden"]
    )
    assert (args.profile, args.reader, args.include_hidden) == ("ava-hd", "powerpoint", True)
    with pytest.raises(SystemExit):
        cli.build_deck_parser().parse_args(["synth", "d.pptx", "--reader", "libreoffice"])


# ---- phase 5: reruns only redo what changed ----


def test_a_rerun_synthesizes_only_the_changed_slide(local, client, transport, tmp_path):
    from decks import CONTOSO_SLIDES

    deck_path = make_deck(tmp_path / "contoso.pptx")
    first = read_manifest(synth([str(deck_path)], local, client))
    assert len(transport.requests) == 2
    transport.requests.clear()

    # Same deck again: every slide's audio is reused, no Azure call.
    again = read_manifest(synth([str(deck_path)], local, client))
    assert transport.requests == []
    assert again["slides"] == first["slides"]

    # Slide 4's notes change: only slide 4 is synthesized.
    changed = [list(slide) for slide in CONTOSO_SLIDES]
    changed[3][1] = "The migration moved to December."
    make_deck(deck_path, [tuple(slide) for slide in changed])
    third = read_manifest(synth([str(deck_path)], local, client))
    (request,) = transport.requests
    assert "December" in request.content.decode()
    assert third["slides"][0] == first["slides"][0]
    assert third["slides"][1]["hash"] != first["slides"][1]["hash"]


def test_a_profile_change_redoes_every_slide(local, client, transport, contoso):
    synth([str(contoso)], local, client)
    transport.requests.clear()
    synth([str(contoso), "--profile", "ava-hd-steady"], local, client)
    assert len(transport.requests) == 2


def test_overwrite_redoes_everything(local, client, transport, contoso):
    synth([str(contoso)], local, client)
    transport.requests.clear()
    synth([str(contoso), "--overwrite"], local, client)
    assert len(transport.requests) == 2


def test_audio_of_a_slide_without_notes_any_more_is_removed(local, client, transport, tmp_path):
    deck_path = make_deck(tmp_path / "talk.pptx", [("A", "One.", False), ("B", "Two.", False)])
    synth([str(deck_path)], local, client)
    folder = tmp_path / "output" / "talk"
    assert (folder / "slide-02.mp3").exists()
    make_deck(deck_path, [("A", "One.", False), ("B", None, False)])
    manifest = read_manifest(synth([str(deck_path)], local, client))
    assert not (folder / "slide-02.mp3").exists()
    assert [s["slide"] for s in manifest["slides"]] == [1]


def test_a_file_the_tool_did_not_write_is_still_protected(local, client, contoso, tmp_path):
    synth([str(contoso)], local, client)
    (tmp_path / "output" / "contoso" / "slide-01.ssml").unlink(missing_ok=True)
    (tmp_path / "output" / "contoso" / "slide-02.mp3").write_bytes(b"mine")  # not in the manifest
    make_deck(contoso, [("A", "x", False), ("B", "Now with notes.", False)])
    with pytest.raises(TtsError, match="slide-02.mp3 already exists"):
        synth([str(contoso)], local, client)


def test_a_manifest_for_another_deck_is_refused(local, client, contoso, tmp_path):
    synth([str(contoso)], local, client)
    other = make_deck(tmp_path / "other.pptx")
    with pytest.raises(TtsError, match="is for contoso.pptx, not other.pptx"):
        synth([str(other), "--out", str(tmp_path / "output" / "contoso")], local, client)
