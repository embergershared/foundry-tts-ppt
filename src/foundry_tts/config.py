"""Settings: the TOML files and the environment variables. The only module that reads either."""

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path

from dotenv import load_dotenv

from foundry_tts.errors import TtsError
from foundry_tts.profiles import Profile, validate

DEFAULT_CONFIG_FILE = "foundry-tts.toml"
DEFAULT_ENV_FILE = ".env"


@dataclass(frozen=True)
class SpeechSettings:
    language: str
    output_format: str
    paragraph_break_ms: int
    endpoint_template: str
    max_chars_per_request: int


@dataclass(frozen=True)
class OpenAiSettings:
    response_format: str
    max_input_chars: int


@dataclass(frozen=True)
class DeckSettings:
    cue_pause_ms: int
    audio_shape_name: str
    off_slide_margin_points: float


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
    deck: DeckSettings
    http: HttpSettings
    output_folder: Path
    azure: AzureSettings
    profiles: Mapping[str, Profile]
    default_profile: str
    lexicon: Mapping[str, str]

    def profile(self, name: str) -> Profile:
        try:
            return self.profiles[name]
        except KeyError:
            raise TtsError(
                f"Unknown profile '{name}'. Profiles: {', '.join(sorted(self.profiles))}."
            ) from None

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


def _read_toml(path: Path) -> Mapping:
    if not path.is_file():
        raise TtsError(f"Settings file not found: {path}")
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise TtsError(f"{path} is not valid TOML: {error}") from error


def _section(data: Mapping, name: str, path: Path) -> Mapping:
    section = data.get(name)
    if not isinstance(section, Mapping):
        raise TtsError(f"Section [{name}] is missing from {path}.")
    return section


def _check_type(key: str, value, kind: type, where: str):
    if kind is float and isinstance(value, int) and not isinstance(value, bool):
        value = float(value)
    if not isinstance(value, kind) or isinstance(value, bool):
        raise TtsError(f"Setting {key} in {where} must be a {kind.__name__}.")
    return value


def _value(section: Mapping, key: str, kind: type, where: str):
    if key not in section:
        raise TtsError(f"Setting {key} is missing from {where}.")
    return _check_type(key, section[key], kind, where)


# Type of each optional profile setting (name, engine and voice are required strings).
_PROFILE_OPTIONAL = {
    "language": str,
    "style": str,
    "rate": str,
    "pitch": str,
    "temperature": float,
    "instructions": str,
}
_PROFILE_KEYS = {field.name for field in fields(Profile)} - {"name"}


def _profiles(data: Mapping, path: Path) -> dict[str, Profile]:
    table = _section(data, "profiles", path)
    profiles = {}
    for name, entry in table.items():
        where = f"[profiles.{name}] of {path}"
        if not isinstance(entry, Mapping):
            raise TtsError(f"{where} must be a table.")
        unknown = set(entry) - _PROFILE_KEYS
        if unknown:
            raise TtsError(f"{where}: unknown setting(s) {', '.join(sorted(unknown))}.")
        profile = Profile(
            name=name,
            engine=_value(entry, "engine", str, where),
            voice=_value(entry, "voice", str, where),
            **{
                key: _check_type(key, entry[key], kind, where)
                for key, kind in _PROFILE_OPTIONAL.items()
                if key in entry
            },
        )
        validate(profile)
        profiles[name] = profile
    if not profiles:
        raise TtsError(f"[profiles] of {path} has no profile.")
    return profiles


def _lexicon(data: Mapping, path: Path) -> dict[str, str]:
    table = data.get("lexicon", {})
    if not isinstance(table, Mapping):
        raise TtsError(f"[lexicon] of {path} must be a table.")
    for word, said in table.items():
        if not isinstance(said, str) or not said.strip() or not word.strip():
            raise TtsError(f"[lexicon] of {path}: {word!r} must map to a non-empty string.")
    return dict(table)


def load_lexicon(path: Path) -> dict[str, str]:
    """The [lexicon] table of an extra pronunciation file (--lexicon)."""
    data = _read_toml(path)
    if "lexicon" not in data:
        raise TtsError(f"{path} has no [lexicon] table.")
    return _lexicon(data, path)


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

    data = _read_toml(config_path)
    defaults = _section(data, "defaults", config_path)
    speech = _section(data, "speech", config_path)
    openai = _section(data, "openai", config_path)
    deck = _section(data, "deck", config_path)
    http = _section(data, "http", config_path)
    output = _section(data, "output", config_path)

    def where(name: str) -> str:
        return f"[{name}] of {config_path}"

    profiles = _profiles(data, config_path)
    default_profile = _value(defaults, "profile", str, where("defaults"))
    if default_profile not in profiles:
        raise TtsError(f"{where('defaults')}: profile '{default_profile}' isn't defined.")

    return Settings(
        speech=SpeechSettings(
            language=_value(speech, "language", str, where("speech")),
            output_format=_value(speech, "output_format", str, where("speech")),
            paragraph_break_ms=_value(speech, "paragraph_break_ms", int, where("speech")),
            endpoint_template=_value(speech, "endpoint_template", str, where("speech")),
            max_chars_per_request=_value(speech, "max_chars_per_request", int, where("speech")),
        ),
        openai=OpenAiSettings(
            response_format=_value(openai, "response_format", str, where("openai")),
            max_input_chars=_value(openai, "max_input_chars", int, where("openai")),
        ),
        deck=DeckSettings(
            cue_pause_ms=_value(deck, "cue_pause_ms", int, where("deck")),
            audio_shape_name=_value(deck, "audio_shape_name", str, where("deck")),
            off_slide_margin_points=_value(deck, "off_slide_margin_points", float, where("deck")),
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
        profiles=profiles,
        default_profile=default_profile,
        lexicon=_lexicon(data, config_path),
    )
