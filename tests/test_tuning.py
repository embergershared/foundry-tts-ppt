"""What the demo's tuning window asks of the tool: overrides, profile list/check/save, a sample."""

import io
import json
import shutil
from dataclasses import replace
from datetime import datetime

import pytest
from conftest import CONFIG, ENV, FAKE_AUDIO, fake_token
from decks import make_deck

from foundry_tts import cli
from foundry_tts.config import load_settings, save_profile
from foundry_tts.errors import TtsError
from foundry_tts.profiles import Profile

NOW = datetime(2026, 11, 23, 9, 0, 0)


@pytest.fixture
def local(settings, tmp_path):
    return replace(settings, output_folder=tmp_path / "output")


@pytest.fixture
def contoso(tmp_path):
    return make_deck(tmp_path / "contoso.pptx")


@pytest.fixture
def config_copy(tmp_path):
    """A copy of the repository's settings file, which profile save may change."""
    path = tmp_path / "foundry-tts.toml"
    shutil.copyfile(CONFIG, path)
    return path


def sent(transport, index=0) -> str:
    return transport.requests[index].content.decode()


def deck(argv, settings, client):
    args = cli.build_deck_parser().parse_args(argv)
    return cli.run_deck(args, settings, client=client, get_token=fake_token, now=NOW)


def profile_command(argv) -> tuple[int, dict | None]:
    stdout = io.StringIO()
    code = cli.profile_main(argv, stdout)
    return code, json.loads(stdout.getvalue()) if stdout.getvalue() else None


# ---- overrides on the command line ----


def test_style_rate_pitch_and_temperature_override_the_profile(local, client, transport, contoso):
    deck(
        ["synth", str(contoso), "--profile", "ava-hd-steady", "--style=narrator", "--rate=-10%",
         "--pitch=+2st", "--temperature=0.3"],
        local, client,
    )  # fmt: skip
    ssml = sent(transport)
    assert '<mstts:express-as style="narrator">' in ssml
    assert 'rate="-10%"' in ssml and 'pitch="+2st"' in ssml
    assert 'parameters="temperature=0.3"' in ssml


def test_volume_and_a_rate_multiplier_override_the_profile(local, client, transport, contoso):
    deck(
        ["synth", str(contoso), "--profile", "andrew-hd", "--rate", "1.2", "--volume=-10"],
        local,
        client,
    )  # noqa: E501
    assert '<prosody rate="1.2" volume="-10">' in sent(transport)


def test_an_override_the_voice_family_refuses_stops_before_azure(
    local, client, transport, contoso
):
    with pytest.raises(TtsError, match="temperature applies to HD voices only"):
        deck(
            ["synth", str(contoso), "--profile", "harper-narrator", "--temperature=0.5"],
            local,
            client,
        )
    assert transport.requests == []


def test_overrides_apply_to_one_profile_only(local, client):
    args = cli.build_parser().parse_args(
        ["--text", "Hi", "--profile", "ava-hd", "--profile", "andrew-hd", "--rate=-5%"]
    )
    with pytest.raises(TtsError, match="--rate.* apply to one profile only"):
        cli.choose_profiles(args, local)


# ---- profile list, check, save ----


def test_profile_list_gives_every_profile_and_what_its_voice_accepts():
    code, result = profile_command(["list", "--config", str(CONFIG)])
    assert code == 0
    assert result["default"] == "andrew-hd"
    profiles = {item["name"]: item for item in result["profiles"]}
    assert profiles["ava-hd-steady"]["settings"] == {"rate": "-5%", "temperature": 0.6}
    assert "temperature" in profiles["andrew-hd"]["applies"]
    assert "temperature" not in profiles["harper-narrator"]["applies"]  # a MAI-Voice voice
    assert "volume" in profiles["harper-narrator"]["applies"]  # every speech family (measured)
    assert profiles["marin-presenter"]["applies"] == ["instructions"]
    assert profiles["marin-presenter"]["family"] is None


def test_profile_check_gives_the_profile_with_its_overrides():
    code, result = profile_command(
        ["check", "--profile", "andrew-hd", "--rate=-5%", "--style=narrator", "--config",
         str(CONFIG)]
    )  # fmt: skip
    assert code == 0
    assert result["settings"] == {"style": "narrator", "rate": "-5%"}


def test_profile_check_reports_why_not(caplog):
    code, result = profile_command(
        ["check", "--profile", "marin-presenter", "--rate=-5%", "--config", str(CONFIG)]
    )
    assert (code, result) == (1, None)
    assert "rate doesn't apply to the openai engine" in caplog.text


def test_profile_save_adds_a_profile_above_the_lexicon(config_copy):
    code, result = profile_command(
        ["save", "andrew-slow", "--profile", "andrew-hd", "--rate=-10%", "--temperature=0.5",
         "--volume", "80", "--config", str(config_copy)]
    )  # fmt: skip
    assert code == 0
    assert result["name"] == "andrew-slow"

    saved = load_settings(config_copy, env=ENV)
    profile = saved.profile("andrew-slow")
    assert (profile.voice, profile.rate, profile.temperature, profile.volume) == (
        "en-US-Andrew:DragonHDLatestNeural",
        "-10%",
        0.5,
        "80",
    )
    assert saved.lexicon["AKS"] == "A K S"  # the lexicon is still a table of its own
    text = config_copy.read_text(encoding="utf-8")
    assert text.index("[profiles.andrew-slow]") < text.index("# ---- Pronunciation")
    assert "# ---- Voice profiles" in text  # comments kept


@pytest.mark.parametrize(
    ("name", "message"),
    [("andrew-hd", "already exists"), ("my profile", "may only use letters")],
)
def test_profile_save_refuses_a_bad_name(config_copy, caplog, name, message):
    before = config_copy.read_bytes()
    code, _ = profile_command(["save", name, "--config", str(config_copy)])
    assert code == 1
    assert message in caplog.text
    assert config_copy.read_bytes() == before


def test_save_profile_keeps_line_endings_and_escapes_text(tmp_path):
    path = tmp_path / "settings.toml"
    path.write_bytes(CONFIG.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    profile = Profile(
        name="presenter-fr",
        engine="openai",
        voice="marin",
        instructions='Calme, "posé", avec une pause\naprès chaque phrase.',
    )
    save_profile(path, profile)
    raw = path.read_bytes()
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
    assert load_settings(path, env=ENV).profile("presenter-fr") == profile


def test_save_profile_without_a_lexicon_appends_at_the_end(tmp_path):
    text = CONFIG.read_text(encoding="utf-8")
    path = tmp_path / "settings.toml"
    path.write_text(text[: text.index("# ---- Pronunciation")].rstrip(), encoding="utf-8")
    save_profile(
        path,
        Profile(
            name="ava-fast", engine="speech", voice="en-US-Ava:DragonHDLatestNeural", rate="+10%"
        ),
    )
    assert load_settings(path, env=ENV).profile("ava-fast").rate == "+10%"


# ---- deck sample ----


def test_sample_speaks_the_first_narrated_slide(local, client, transport, contoso, tmp_path):
    path = deck(["sample", str(contoso), "--rate=-5%"], local, client)

    assert path == tmp_path / "output" / "contoso" / "sample.mp3"
    assert path.read_bytes() == FAKE_AUDIO
    assert len(transport.requests) == 1  # one slide, not the deck
    assert 'rate="-5%"' in sent(transport)
    assert "Welcome to the Contoso cloud roadmap" in sent(transport)  # slide 1, cleaned


def test_sample_of_a_deck_whose_name_ends_with_a_space(local, client, transport, tmp_path):
    """Issue #39: the sample failed with FileNotFoundError on 'Contoso review .pptx'."""
    spaced = make_deck(tmp_path / "Contoso review .pptx")
    path = deck(["sample", str(spaced)], local, client)
    assert path == tmp_path / "output" / "Contoso review" / "sample.mp3"
    assert path.read_bytes() == FAKE_AUDIO


def test_sample_of_a_chosen_slide_even_hidden(local, client, transport, contoso):
    deck(["sample", str(contoso), "--slide", "3"], local, client)
    assert "backup slide only" in sent(transport)


def test_sample_replaces_the_last_one_and_leaves_deck_synth_alone(
    local, client, transport, contoso, tmp_path
):
    deck(["sample", str(contoso)], local, client)
    deck(["sample", str(contoso)], local, client)  # no --overwrite needed
    manifest = deck(["synth", str(contoso)], local, client)
    folder = tmp_path / "output" / "contoso"
    assert manifest == folder / "manifest.json"
    assert sorted(p.name for p in folder.iterdir()) == [
        "manifest.json",
        "sample.mp3",
        "slide-01.mp3",
        "slide-04.mp3",
    ]


@pytest.mark.parametrize(
    ("slide", "message"), [("2", "Slide 2 .* no speaker notes"), ("9", "Slide 9")]
)
def test_sample_of_a_slide_without_notes_is_refused(
    local, client, transport, contoso, slide, message
):
    with pytest.raises(TtsError, match=message):
        deck(["sample", str(contoso), "--slide", slide], local, client)
    assert transport.requests == []
