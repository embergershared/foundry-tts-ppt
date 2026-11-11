from pathlib import Path

import pytest
from conftest import CONFIG, ENV, RESOURCE_ID

from foundry_tts.config import load_settings
from foundry_tts.errors import TtsError


def test_repository_settings_file_loads(settings):
    assert settings.speech.voice == "en-US-Ava:DragonHDLatestNeural"
    assert settings.speech.output_format.endswith("mp3")
    assert settings.openai.max_input_chars == 4096
    assert settings.http.timeout_seconds == 120.0
    assert settings.output_folder == Path("output")


def test_speech_url_is_built_from_the_region(settings):
    assert settings.speech_url() == "https://eastus2.tts.speech.microsoft.com/cognitiveservices/v1"
    assert settings.speech_resource_id() == RESOURCE_ID


def test_speech_endpoint_variable_replaces_the_regional_url():
    env = {**ENV, "FOUNDRY_SPEECH_ENDPOINT": "https://example.test/tts"}
    assert load_settings(CONFIG, env=env).speech_url() == "https://example.test/tts"


def test_openai_url_has_no_double_slash(settings):
    assert settings.openai_speech_url() == (
        "https://fdy-test.openai.azure.com/openai/v1/audio/speech"
    )
    assert settings.openai_deployment() == "gpt-4o-mini-tts"


@pytest.mark.parametrize(
    ("missing", "call"),
    [
        ("FOUNDRY_REGION", "speech_url"),
        ("FOUNDRY_RESOURCE_ID", "speech_resource_id"),
        ("FOUNDRY_OPENAI_ENDPOINT", "openai_speech_url"),
        ("FOUNDRY_TTS_DEPLOYMENT", "openai_deployment"),
    ],
)
def test_a_missing_variable_is_named_when_its_engine_needs_it(missing, call):
    env = {k: v for k, v in ENV.items() if k != missing}
    settings = load_settings(CONFIG, env=env)  # loading works: other engines may not need it
    with pytest.raises(TtsError, match=missing):
        getattr(settings, call)()


def test_missing_settings_file_is_reported(tmp_path):
    with pytest.raises(TtsError, match="not found"):
        load_settings(tmp_path / "nope.toml", env=ENV)


def test_missing_or_mistyped_setting_is_reported(tmp_path):
    text = CONFIG.read_text(encoding="utf-8")
    broken = tmp_path / "broken.toml"
    broken.write_text(text.replace("paragraph_break_ms = 400", 'paragraph_break_ms = "x"'))
    with pytest.raises(TtsError, match="paragraph_break_ms.*int"):
        load_settings(broken, env=ENV)
    broken.write_text(text.replace("[http]", "[web]"))
    with pytest.raises(TtsError, match=r"\[http\]"):
        load_settings(broken, env=ENV)


def test_env_file_is_loaded_without_overriding_the_environment(tmp_path, monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FOUNDRY_REGION", "westus2")
    env_file = tmp_path / ".env"
    env_file.write_text("FOUNDRY_REGION=eastus2\nFOUNDRY_TTS_DEPLOYMENT=my-tts\n")
    settings = load_settings(CONFIG, env_file=env_file)
    assert settings.azure.region == "westus2"
    assert settings.azure.tts_deployment == "my-tts"
