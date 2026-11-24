import io
import json

import httpx
import pytest
from conftest import RESOURCE_ID, RecordingTransport, fake_token

from foundry_tts import cli, engines, voices
from foundry_tts.errors import TtsError

# Entries shaped as the voice list API returns them (fields the tool doesn't read left out).
API_VOICES = [
    {
        "ShortName": "en-US-Grant:MAI-Voice-2.1",
        "DisplayName": "Grant MAI-Voice-2.1",
        "Locale": "en-US",
        "LocaleName": "English (United States)",
        "Gender": "Male",
        "Status": "Preview",
        "StyleList": ["agent", "audiobook", "educational", "narrator"],
        "VoiceTag": {"ModelSeries": ["MAI-Voice-2.1"], "Source": ["MAI"]},
    },
    {
        "ShortName": "en-US-Ava:DragonHDLatestNeural",
        "DisplayName": "Ava Dragon HD Latest",
        "Locale": "en-US",
        "LocaleName": "English (United States)",
        "Gender": "Female",
        "Status": "GA",
        "VoiceTag": {
            "ModelSeries": ["HDLatest"],
            "VoicePersonalities": ["Pleasant", "Friendly"],
            "TailoredScenarios": ["Chat", "News"],
        },
    },
    {
        "ShortName": "fr-FR-DeniseNeural",
        "DisplayName": "Denise",
        "Locale": "fr-FR",
        "LocaleName": "French (France)",
        "Gender": "Female",
        "Status": "GA",
        "StyleList": ["cheerful", "sad"],
        "VoiceTag": {"ModelSeries": ["Monolingual"]},
    },
    {
        "ShortName": "en-GB-SoniaNeural",
        "Locale": "en-GB",
        "Gender": "Female",
        "Status": "GA",
    },
    {
        "ShortName": "en-US-Andrew:DragonHDOmniLatestNeural",
        "DisplayName": "Andrew Dragon HD Omni Latest",
        "Locale": "en-US",
        "Gender": "Male",
        "Status": "Preview",
        "StyleList": ["calm"],
        "VoiceTag": {"ModelSeries": ["HDOmniLatest"]},
    },
]


@pytest.fixture
def offered():
    return voices.parse(API_VOICES)


def names(selected):
    return [voice.name for voice in selected]


def test_parse_reads_each_voice_and_sorts_by_language_then_name(offered):
    assert names(offered) == [
        "en-GB-SoniaNeural",
        "en-US-Andrew:DragonHDOmniLatestNeural",
        "en-US-Ava:DragonHDLatestNeural",
        "en-US-Grant:MAI-Voice-2.1",
        "fr-FR-DeniseNeural",
    ]
    grant = offered[3]
    assert grant == voices.Voice(
        name="en-US-Grant:MAI-Voice-2.1",
        display_name="Grant MAI-Voice-2.1",
        locale="en-US",
        locale_name="English (United States)",
        gender="Male",
        family="MAI-Voice",
        model="MAI-Voice-2.1",
        status="Preview",
        styles=("agent", "audiobook", "educational", "narrator"),
        personalities=(),
        scenarios=(),
    )
    assert [voice.family for voice in offered] == [
        "standard",
        "Dragon HD Omni",
        "Dragon HD",
        "MAI-Voice",
        "standard",
    ]


def test_parse_fills_missing_details_with_empty_values(offered):
    sonia = offered[0]
    assert sonia.display_name == "en-GB-SoniaNeural"
    assert (sonia.model, sonia.locale_name, sonia.styles) == ("", "", ())


def test_parse_refuses_a_voice_without_a_name():
    with pytest.raises(TtsError, match="without a ShortName"):
        voices.parse([{"Locale": "en-US"}])


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({}, 5),
        ({"language": "en-US"}, 3),
        ({"language": "EN-us"}, 3),
        ({"language": "en"}, 4),  # every en-* locale
        ({"language": "e"}, 0),  # a language is a whole code, not a prefix of one
        ({"gender": "female"}, 3),
        ({"family": "dragon hd"}, 1),  # not Dragon HD Omni
        ({"language": "en-US", "gender": "Male"}, 2),
        ({"search": "grant"}, 1),
        ({"search": "NARRATOR"}, 1),  # a style
        ({"search": "friendly"}, 1),  # a personality
        ({"search": "news"}, 1),  # a scenario
        ({"search": "Dragon HD"}, 2),  # the display name
    ],
)
def test_select_keeps_the_voices_that_pass_every_filter(offered, filters, expected):
    assert len(voices.select(offered, **filters)) == expected


def test_describe_and_to_dict(offered):
    grant = offered[3]
    line = grant.describe()
    assert line.startswith("en-US-Grant:MAI-Voice-2.1 ")
    assert "Male" in line and "MAI-Voice" in line and "Preview" in line
    assert line.endswith("styles: agent, audiobook, educational, narrator")
    assert offered[0].describe().endswith("styles: -")
    assert grant.to_dict()["styles"] == ("agent", "audiobook", "educational", "narrator")


def test_list_speech_voices_gets_the_list_with_an_entra_token(settings):
    transport = RecordingTransport(content=json.dumps(API_VOICES).encode())
    with httpx.Client(transport=transport) as client:
        listed = engines.list_speech_voices(settings, client, fake_token)

    assert listed == API_VOICES
    (request,) = transport.requests
    assert request.method == "GET"
    assert str(request.url) == (
        "https://eastus2.tts.speech.microsoft.com/cognitiveservices/voices/list"
    )
    assert request.headers["Authorization"] == f"Bearer aad#{RESOURCE_ID}#entra-token"
    assert request.headers["User-Agent"] == "foundry-tts"


@pytest.mark.parametrize(
    ("status", "content", "message"),
    [
        (401, b"Unauthorized", "HTTP 401"),
        (200, b"<html>", "isn't JSON"),
        (200, b'{"voices": []}', "isn't a JSON array"),
    ],
)
def test_list_speech_voices_reports_a_bad_answer(settings, status, content, message):
    with (
        httpx.Client(transport=RecordingTransport(status, content)) as client,
        pytest.raises(TtsError, match=message),
    ):
        engines.list_speech_voices(settings, client, fake_token)


def test_list_speech_voices_reports_an_unreachable_service(settings):
    def fail(request):
        raise httpx.ConnectError("no route", request=request)

    with (
        httpx.Client(transport=httpx.MockTransport(fail)) as client,
        pytest.raises(TtsError, match="Could not reach Azure Speech"),
    ):
        engines.list_speech_voices(settings, client, fake_token)


def run_voice(argv, settings):
    args = cli.build_voice_parser().parse_args(["list", *argv])
    transport = RecordingTransport(content=json.dumps(API_VOICES).encode())
    with httpx.Client(transport=transport) as client:
        return args, cli.run_voice(args, settings, client=client, get_token=fake_token)


def test_voice_list_applies_the_filters_given(settings):
    _, selected = run_voice(
        ["--language", "en-US", "--gender", "Male", "--family", "mai-voice"], settings
    )
    assert names(selected) == ["en-US-Grant:MAI-Voice-2.1"]


def test_voice_list_writes_one_line_per_voice_or_json(settings):
    args, selected = run_voice(["--search", "narrator"], settings)
    text = io.StringIO()
    cli.write_voices(selected, text, as_json=args.json)
    assert text.getvalue().splitlines() == [selected[0].describe()]

    args, selected = run_voice(["--language", "fr", "--json"], settings)
    out = io.StringIO()
    cli.write_voices(selected, out, as_json=args.json)
    (denise,) = json.loads(out.getvalue())["voices"]
    assert denise["name"] == "fr-FR-DeniseNeural"
    assert denise["styles"] == ["cheerful", "sad"]


@pytest.mark.parametrize("argv", [["--family", "HD"], ["--gender", "other"]])
def test_voice_list_refuses_an_unknown_family_or_gender(argv, capsys):
    with pytest.raises(SystemExit):
        cli.build_voice_parser().parse_args(["list", *argv])
    assert "error: argument --" in capsys.readouterr().err
