import json
import logging
from datetime import datetime

import pytest
from conftest import CONFIG, FAKE_AUDIO, fake_token
from test_audio_file import FakeStdin

from foundry_tts import cli
from foundry_tts.errors import TtsError

NOW = datetime(2026, 11, 10, 12, 0, 0)


def run(argv, settings, client, stdin=None, tmp_path=None):
    args = cli.build_parser().parse_args(argv)
    if tmp_path is not None:
        settings = settings.__class__(**{**vars(settings), "output_folder": tmp_path / "output"})
    return cli.run(
        args,
        settings,
        client=client,
        get_token=fake_token,
        stdin=stdin or FakeStdin(tty=True),
        now=NOW,
    )


def test_text_to_speech_file_with_the_default_engine(settings, client, transport, tmp_path):
    out = run(["--text", "Hello & welcome"], settings, client, tmp_path=tmp_path)

    assert out == tmp_path / "output" / "20261110-120000-speech.mp3"
    assert out.read_bytes() == FAKE_AUDIO
    ssml = transport.requests[0].content.decode()
    assert "Hello &amp; welcome" in ssml
    assert 'name="en-US-Ava:DragonHDLatestNeural"' in ssml


def test_voice_option_and_saved_ssml(settings, client, transport, tmp_path):
    out = tmp_path / "hi.mp3"
    run(
        ["--text", "Hi", "--voice", "en-US-Harper:MAI-Voice-2.1", "--out", str(out),
         "--save-ssml"],
        settings, client,
    )  # fmt: skip
    saved = out.with_suffix(".ssml").read_text(encoding="utf-8")
    assert 'name="en-US-Harper:MAI-Voice-2.1"' in saved
    assert saved == transport.requests[0].content.decode()


def test_ssml_file_is_sent_as_is(settings, client, transport, tmp_path):
    ssml_file = tmp_path / "hand.xml"
    ssml_file.write_text("<speak>hand written</speak>", encoding="utf-8")
    run(["--ssml", str(ssml_file), "--out", str(tmp_path / "a.mp3")], settings, client)
    assert transport.requests[0].content == b"<speak>hand written</speak>"


def test_ssml_is_refused_with_the_openai_engine(settings, client, tmp_path):
    ssml_file = tmp_path / "hand.xml"
    ssml_file.write_text("<speak/>", encoding="utf-8")
    with pytest.raises(TtsError, match="speech engine only"):
        run(["--ssml", str(ssml_file), "--engine", "openai"], settings, client)


def test_piped_text_with_the_openai_engine(settings, client, transport, tmp_path):
    out = run(
        ["--engine", "openai", "--instructions", "Whisper."],
        settings, client, stdin=FakeStdin("From a pipe"), tmp_path=tmp_path,
    )  # fmt: skip
    assert out.name == "20261110-120000-openai.mp3"
    body = json.loads(transport.requests[0].content)
    assert body["input"] == "From a pipe"
    assert body["instructions"] == "Whisper."
    assert body["voice"] == "marin"


def test_azure_failure_leaves_no_file(settings, tmp_path):
    import httpx
    from conftest import RecordingTransport

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
