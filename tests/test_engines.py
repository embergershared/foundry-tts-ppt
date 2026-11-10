import json

import httpx
import pytest
from conftest import FAKE_AUDIO, RESOURCE_ID, RecordingTransport, fake_token

from foundry_tts import engines
from foundry_tts.errors import TtsError


def test_speech_posts_ssml_with_entra_token_and_output_format(settings, client, transport):
    audio = engines.synthesize_speech("<speak/>", settings, client, fake_token)

    assert audio == FAKE_AUDIO
    (request,) = transport.requests
    assert str(request.url) == "https://eastus2.tts.speech.microsoft.com/cognitiveservices/v1"
    assert request.headers["Authorization"] == f"Bearer aad#{RESOURCE_ID}#entra-token"
    assert request.headers["Content-Type"].startswith("application/ssml+xml")
    assert request.headers["X-Microsoft-OutputFormat"] == settings.speech.output_format
    assert request.headers["User-Agent"] == "foundry-tts"
    assert request.content == b"<speak/>"


def test_openai_posts_json_with_deployment_voice_and_instructions(settings, client, transport):
    audio = engines.synthesize_openai(
        "Hello",
        voice="marin",
        instructions="Calm.",
        settings=settings,
        client=client,
        get_token=fake_token,
    )

    assert audio == FAKE_AUDIO
    (request,) = transport.requests
    assert str(request.url) == "https://fdy-test.openai.azure.com/openai/v1/audio/speech"
    assert request.headers["Authorization"] == "Bearer entra-token"
    assert json.loads(request.content) == {
        "model": "gpt-4o-mini-tts",
        "input": "Hello",
        "voice": "marin",
        "response_format": "mp3",
        "instructions": "Calm.",
    }


def test_openai_sends_no_instructions_when_empty(settings, client, transport):
    engines.synthesize_openai(
        "Hi",
        voice="cedar",
        instructions="",
        settings=settings,
        client=client,
        get_token=fake_token,
    )
    assert "instructions" not in json.loads(transport.requests[0].content)


def test_openai_refuses_text_over_the_limit_before_calling_azure(settings, client, transport):
    too_long = "a" * (settings.openai.max_input_chars + 1)
    with pytest.raises(TtsError, match="at most 4096"):
        engines.synthesize_openai(
            too_long, voice="v", instructions="", settings=settings, client=client,
            get_token=fake_token,
        )  # fmt: skip
    assert transport.requests == []


@pytest.mark.parametrize(
    ("status", "content", "message"),
    [
        (401, b"Unauthorized: token invalid", "HTTP 401.*token invalid"),
        (400, b"", "HTTP 400.*Bad Request"),
        (200, b"", "empty audio"),
    ],
)
def test_speech_errors_stop_with_status_and_detail(settings, status, content, message):
    with (
        httpx.Client(transport=RecordingTransport(status, content)) as client,
        pytest.raises(TtsError, match=message),
    ):
        engines.synthesize_speech("<speak/>", settings, client, fake_token)


def test_network_failure_is_reported(settings):
    def fail(request):
        raise httpx.ConnectError("no route", request=request)

    with (
        httpx.Client(transport=httpx.MockTransport(fail)) as client,
        pytest.raises(TtsError, match="Could not reach Azure Speech"),
    ):
        engines.synthesize_speech("<speak/>", settings, client, fake_token)


@pytest.mark.parametrize(
    ("output_format", "extension"),
    [("audio-24khz-160kbitrate-mono-mp3", ".mp3"), ("riff-24khz-16bit-mono-pcm", ".wav")],
)
def test_speech_extension(output_format, extension):
    assert engines.speech_extension(output_format) == extension


def test_unsupported_formats_are_refused():
    with pytest.raises(TtsError, match="not supported"):
        engines.speech_extension("ogg-24khz-16bit-mono-opus")
    with pytest.raises(TtsError, match="not supported"):
        engines.openai_extension("pcm")
    assert engines.openai_extension("wav") == ".wav"
