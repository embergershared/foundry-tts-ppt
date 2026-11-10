"""Settings: the TOML file and the environment variables. The only module that reads either."""

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from foundry_tts.errors import TtsError

DEFAULT_CONFIG_FILE = "foundry-tts.toml"
DEFAULT_ENV_FILE = ".env"


@dataclass(frozen=True)
class SpeechSettings:
    voice: str
    language: str
    output_format: str
    paragraph_break_ms: int
    endpoint_template: str


@dataclass(frozen=True)
class OpenAiSettings:
    voice: str
    instructions: str
    response_format: str
    max_input_chars: int


@dataclass(frozen=True)
class HttpSettings:
    timeout_seconds: float
    user_agent: str


@dataclass(frozen=True)
class AzureSettings:
    """Values that depend on the deployed resource (environment variables or .env)."""

    resource_id: str | None
    region: str | None
    speech_endpoint: str | None
    openai_endpoint: str | None
    tts_deployment: str | None


@dataclass(frozen=True)
class Settings:
    speech: SpeechSettings
    openai: OpenAiSettings
    http: HttpSettings
    output_folder: Path
    azure: AzureSettings

    def speech_url(self) -> str:
        """The text to speech URL: FOUNDRY_SPEECH_ENDPOINT, else the regional one."""
        if self.azure.speech_endpoint:
            return self.azure.speech_endpoint
        region = _required(self.azure.region, "FOUNDRY_REGION", "speech")
        return self.speech.endpoint_template.format(region=region)

    def speech_resource_id(self) -> str:
        return _required(self.azure.resource_id, "FOUNDRY_RESOURCE_ID", "speech")

    def openai_speech_url(self) -> str:
        endpoint = _required(self.azure.openai_endpoint, "FOUNDRY_OPENAI_ENDPOINT", "openai")
        return f"{endpoint.rstrip('/')}/openai/v1/audio/speech"

    def openai_deployment(self) -> str:
        return _required(self.azure.tts_deployment, "FOUNDRY_TTS_DEPLOYMENT", "openai")


def _required(value: str | None, name: str, engine: str) -> str:
    if not value:
        raise TtsError(
            f"{name} is not set; the {engine} engine needs it. Set it in .env (see .env.example) "
            "or in the environment."
        )
    return value


def _section(data: Mapping, name: str, path: Path) -> Mapping:
    section = data.get(name)
    if not isinstance(section, Mapping):
        raise TtsError(f"Section [{name}] is missing from {path}.")
    return section


def _value(section: Mapping, key: str, kind: type, where: str):
    if key not in section:
        raise TtsError(f"Setting {key} is missing from {where}.")
    value = section[key]
    if kind is float and isinstance(value, int) and not isinstance(value, bool):
        value = float(value)
    if not isinstance(value, kind) or isinstance(value, bool):
        raise TtsError(f"Setting {key} in {where} must be a {kind.__name__}.")
    return value


def load_settings(
    config_path: Path,
    env: Mapping[str, str] | None = None,
    env_file: Path | None = None,
) -> Settings:
    """Reads the TOML settings file and the FOUNDRY_* environment variables.

    `env` replaces os.environ (tests); otherwise `env_file` (default .env in the current folder)
    is loaded first, without overriding variables that are already set.
    """
    if env is None:
        load_dotenv(env_file or Path(DEFAULT_ENV_FILE), override=False)
        env = os.environ

    if not config_path.is_file():
        raise TtsError(f"Settings file not found: {config_path}")
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise TtsError(f"{config_path} is not valid TOML: {error}") from error

    speech = _section(data, "speech", config_path)
    openai = _section(data, "openai", config_path)
    http = _section(data, "http", config_path)
    output = _section(data, "output", config_path)

    def where(name: str) -> str:
        return f"[{name}] of {config_path}"

    return Settings(
        speech=SpeechSettings(
            voice=_value(speech, "voice", str, where("speech")),
            language=_value(speech, "language", str, where("speech")),
            output_format=_value(speech, "output_format", str, where("speech")),
            paragraph_break_ms=_value(speech, "paragraph_break_ms", int, where("speech")),
            endpoint_template=_value(speech, "endpoint_template", str, where("speech")),
        ),
        openai=OpenAiSettings(
            voice=_value(openai, "voice", str, where("openai")),
            instructions=_value(openai, "instructions", str, where("openai")),
            response_format=_value(openai, "response_format", str, where("openai")),
            max_input_chars=_value(openai, "max_input_chars", int, where("openai")),
        ),
        http=HttpSettings(
            timeout_seconds=_value(http, "timeout_seconds", float, where("http")),
            user_agent=_value(http, "user_agent", str, where("http")),
        ),
        output_folder=Path(_value(output, "folder", str, where("output"))),
        azure=AzureSettings(
            resource_id=env.get("FOUNDRY_RESOURCE_ID") or None,
            region=env.get("FOUNDRY_REGION") or None,
            speech_endpoint=env.get("FOUNDRY_SPEECH_ENDPOINT") or None,
            openai_endpoint=env.get("FOUNDRY_OPENAI_ENDPOINT") or None,
            tts_deployment=env.get("FOUNDRY_TTS_DEPLOYMENT") or None,
        ),
    )
