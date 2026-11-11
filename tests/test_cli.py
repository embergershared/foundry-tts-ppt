import io
import json
import logging
from dataclasses import replace
from datetime import datetime

import httpx
import pytest
from conftest import CONFIG, FAKE_AUDIO, RecordingTransport, fake_token
from test_audio_file import FakeStdin

from foundry_tts import cli
from foundry_tts.config import load_settings
from foundry_tts.errors import TtsError

NOW = datetime(2026, 11, 10, 12, 0, 0)
STAMP = "20261110-120000"


@pytest.fixture
def local(settings, tmp_path):
    """Settings that write to tmp_path/output."""
    return replace(settings, output_folder=tmp_path / "output")


def run(argv, settings, client, stdin=None):
    args = cli.build_parser().parse_args(argv)
    return cli.run(
        args,
        settings,
        client=client,
        get_token=fake_token,
        stdin=stdin or FakeStdin(tty=True),
        now=NOW,
    )


def sent(transport, index=0) -> str:
    return transport.requests[index].content.decode()


def test_text_with_the_default_profile(local, client, transport, tmp_path):
    (out,) = run(["--text", "Hello & welcome to AKS"], local, client)

    assert out == tmp_path / "output" / f"{STAMP}-ava-hd.mp3"
    assert out.read_bytes() == FAKE_AUDIO
    ssml = sent(transport)
    assert "Hello &amp; welcome to" in ssml
    assert '<sub alias="A K S">AKS</sub>' in ssml  # lexicon of the settings file
    assert 'name="en-US-Ava:DragonHDLatestNeural"' in ssml


def test_profile_sets_voice_style_and_tuning(local, client, transport):
    run(["--text", "Hi", "--profile", "ava-hd-steady"], local, client)
    ssml = sent(transport)
    assert 'parameters="temperature=0.6"' in ssml
    assert '<prosody rate="-5%">Hi</prosody>' in ssml


def test_voice_override_and_saved_ssml(local, client, transport, tmp_path):
    out = tmp_path / "hi.mp3"
    run(
        ["--text", "Hi", "--profile", "harper-narrator", "--voice", "en-US-Grant:MAI-Voice-2.1",
         "--out", str(out), "--save-ssml"],
        local, client,
    )  # fmt: skip
    saved = out.with_suffix(".ssml").read_text(encoding="utf-8")
    assert 'name="en-US-Grant:MAI-Voice-2.1"' in saved
    assert 'style="narrator"' in saved
    assert saved == sent(transport)


def test_markup_comments_and_pauses(local, client, transport):
    run(["--text", "// skip me\nOne [pause 2s] two"], local, client)
    ssml = sent(transport)
    assert "skip me" not in ssml
    assert 'One <break time="2000ms"/> two' in ssml


def test_extra_lexicon_file_is_added(local, client, transport, tmp_path):
    extra = tmp_path / "deck.toml"
    extra.write_text('[lexicon]\nKQL = "K Q L"\n', encoding="utf-8")
    run(["--text", "KQL on AKS", "--lexicon", str(extra)], local, client)
    ssml = sent(transport)
    assert '<sub alias="K Q L">KQL</sub>' in ssml
    assert '<sub alias="A K S">AKS</sub>' in ssml


def test_compare_profiles_writes_one_file_each(local, client, transport, tmp_path):
    paths = run(
        ["--text", "Hello AKS [pause 1s] team", "--profile", "ava-hd",
         "--profile", "harper-narrator", "--profile", "marin-presenter"],
        local, client,
    )  # fmt: skip
    folder = tmp_path / "output"
    assert paths == [
        folder / f"{STAMP}-ava-hd.mp3",
        folder / f"{STAMP}-harper-narrator.mp3",
        folder / f"{STAMP}-marin-presenter.mp3",
    ]
    assert all(path.read_bytes() == FAKE_AUDIO for path in paths)
    assert "<break" in sent(transport, 0)
    assert "<break" not in sent(transport, 1)  # MAI-Voice ignores breaks
    openai_body = json.loads(sent(transport, 2))
    assert openai_body["input"] == "Hello A K S ... team"
    assert openai_body["voice"] == "marin"
    assert openai_body["instructions"].startswith("Calm, confident")


def test_compare_into_a_given_folder(local, client, tmp_path):
    folder = tmp_path / "compare"
    paths = run(
        ["--text", "Hi", "--profile", "ava-hd", "--profile", "ava-hd-steady",
         "--out", str(folder)],
        local, client,
    )  # fmt: skip
    assert [path.parent for path in paths] == [folder, folder]


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--profile", "a", "--profile", "b", "--voice", "x"], "one profile only"),
        (["--profile", "ava-hd", "--profile", "ava-hd"], "more than once"),
        (["--profile", "nope"], "Unknown profile"),
        (["--profile", "ava-hd", "--profile", "ava-hd-steady", "--out", "x.mp3"], "is a folder"),
        (["--profile", "marin-presenter", "--language", "fr-FR"], "language doesn't apply"),
        (["--profile", "harper-narrator", "--instructions", "Calm"], "instructions doesn't apply"),
    ],
)
def test_bad_profile_options_are_refused_before_calling_azure(
    local, client, transport, argv, message
):
    with pytest.raises(TtsError, match=message):
        run(["--text", "Hi", *argv], local, client)
    assert transport.requests == []


def test_ssml_file_is_sent_as_is(local, client, transport, tmp_path):
    ssml_file = tmp_path / "hand.xml"
    ssml_file.write_text("<speak>hand written AKS</speak>", encoding="utf-8")
    run(["--ssml", str(ssml_file), "--out", str(tmp_path / "a.mp3")], local, client)
    assert transport.requests[0].content == b"<speak>hand written AKS</speak>"


@pytest.mark.parametrize(
    ("profiles", "message"),
    [
        (["marin-presenter"], "needs a speech profile"),
        (["ava-hd", "ava-hd-steady"], "one profile"),
    ],
)
def test_ssml_needs_one_speech_profile(local, client, tmp_path, profiles, message):
    ssml_file = tmp_path / "hand.xml"
    ssml_file.write_text("<speak/>", encoding="utf-8")
    argv = ["--ssml", str(ssml_file)] + [x for name in profiles for x in ("--profile", name)]
    with pytest.raises(TtsError, match=message):
        run(argv, local, client)


def test_piped_text_with_an_openai_profile_and_instructions(local, client, transport):
    (out,) = run(
        ["--profile", "marin-presenter", "--instructions", "Whisper."],
        local, client, stdin=FakeStdin("From a pipe"),
    )  # fmt: skip
    assert out.name == f"{STAMP}-marin-presenter.mp3"
    body = json.loads(sent(transport))
    assert (body["input"], body["instructions"]) == ("From a pipe", "Whisper.")


def test_existing_file_stops_the_run_before_any_call(local, client, transport, tmp_path):
    folder = tmp_path / "output"
    folder.mkdir()
    (folder / f"{STAMP}-harper-narrator.mp3").write_bytes(b"old")
    with pytest.raises(TtsError, match="already exists"):
        run(["--text", "Hi", "--profile", "ava-hd", "--profile", "harper-narrator"], local, client)
    assert transport.requests == []


def test_azure_failure_leaves_no_file(settings, tmp_path):
    out = tmp_path / "x.mp3"
    with (
        httpx.Client(transport=RecordingTransport(403, b"Forbidden")) as client,
        pytest.raises(TtsError, match="HTTP 403"),
    ):
        run(["--text", "Hi", "--out", str(out)], settings, client)
    assert not out.exists()


def test_text_and_file_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--text", "a", "--file", "b.txt"])


def test_list_profiles_marks_the_default():
    stdout = io.StringIO()
    cli.list_profiles(load_settings(CONFIG, env={}), stdout)
    lines = stdout.getvalue().splitlines()
    assert lines[0] == "* ava-hd  speech  en-US-Ava:DragonHDLatestNeural"
    assert any(
        line.startswith("  marin-presenter  openai  marin  instructions=") for line in lines
    )


def test_main_lists_profiles_without_azure_settings(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["--list-profiles", "--config", str(CONFIG)]) == 0
    assert "harper-narrator" in capsys.readouterr().out


def test_main_returns_1_and_logs_the_error(tmp_path, caplog, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no .env here
    with caplog.at_level(logging.ERROR):
        code = cli.main(["--text", "Hi", "--config", str(tmp_path / "missing.toml")])
    assert code == 1
    assert "Settings file not found" in caplog.text


def test_main_reports_a_missing_variable_without_calling_azure(tmp_path, monkeypatch, caplog):
    monkeypatch.chdir(tmp_path)
    for name in ("FOUNDRY_RESOURCE_ID", "FOUNDRY_REGION", "FOUNDRY_SPEECH_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cli.engines, "azure_token_provider", lambda: fake_token)
    with caplog.at_level(logging.ERROR):
        code = cli.main(["--text", "Hi", "--config", str(CONFIG)])
    assert code == 1
    assert "FOUNDRY_REGION is not set" in caplog.text
    assert not (tmp_path / "output").exists()
