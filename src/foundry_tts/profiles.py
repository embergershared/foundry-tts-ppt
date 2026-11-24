"""Voice profiles: named voice settings, checked against what their voice family supports.

What each Azure Speech voice family honors was measured against the service on 2026-11-11
(eastus2) by comparing audio lengths, not only taken from the docs, which disagree with it:

| Family         | <break> | <prosody rate> | <sub> | temperature | <prosody volume> |
|----------------|---------|----------------|-------|-------------|------------------|
| Dragon HD      | yes     | yes            | yes   | yes         | yes              |
| Dragon HD Omni | yes     | yes            | yes   | yes         | not measured     |
| MAI-Voice      | ignored | yes            | yes   | not defined | yes              |
| standard       | yes     | yes            | yes   | not defined | yes              |

Volume and the rate multiplier were measured on 2026-11-23 (WAV, same sentence): volume 20 made
the audio 19 to 23% as loud (RMS) and rate 1.5 made it 55 to 66% as long, in every family measured.

Styles (<mstts:express-as>) were accepted by every family; which style names a voice knows
differs per voice and isn't checked here.
"""

import re
from dataclasses import dataclass, replace

from foundry_tts.errors import TtsError

SPEECH = "speech"
OPENAI = "openai"
ENGINES = (SPEECH, OPENAI)

DRAGON_HD = "Dragon HD"
DRAGON_HD_OMNI = "Dragon HD Omni"
MAI_VOICE = "MAI-Voice"
STANDARD = "standard"

# Families whose voices honor <break>, and those that define the temperature parameter.
_BREAK_FAMILIES = {DRAGON_HD, DRAGON_HD_OMNI, STANDARD}
_TEMPERATURE_FAMILIES = {DRAGON_HD, DRAGON_HD_OMNI}
TEMPERATURE_RANGE = (0.0, 1.0)

# <prosody> values (https://learn.microsoft.com/azure/ai-services/speech-service/
# speech-synthesis-markup-voice#adjust-prosody): a relative change ("-5%", "+2st", "+10Hz"), a
# named level, a rate multiplier ("1.2"), or an absolute volume ("75", 0 to 100).
_NUMBER = r"\d+(\.\d+)?"
_RELATIVE = rf"[+-]?{_NUMBER}"
_RATE = re.compile(rf"^({_RELATIVE}%|{_NUMBER}|x-slow|slow|medium|fast|x-fast|default)$")
_PITCH = re.compile(rf"^({_RELATIVE}(%|st|Hz)|x-low|low|medium|high|x-high|default)$")
_VOLUME = re.compile(
    rf"^({_RELATIVE}%|[+-]{_NUMBER}|{_NUMBER}|silent|x-soft|soft|medium|loud|x-loud|default)$"
)
_PLAIN_NUMBER = re.compile(rf"^{_NUMBER}$")
# The documented ranges of a rate multiplier and of an absolute volume.
RATE_MULTIPLIER_RANGE = (0.5, 2.0)
VOLUME_RANGE = (0.0, 100.0)

_SPEECH_ONLY = ("language", "style", "rate", "pitch", "volume", "temperature")
_OPENAI_ONLY = ("instructions",)
# The settings a profile may set besides engine and voice, in the order they are shown.
OPTIONAL_SETTINGS = (
    "language",
    "style",
    "rate",
    "pitch",
    "volume",
    "temperature",
    "instructions",
)


@dataclass(frozen=True)
class Profile:
    name: str
    engine: str
    voice: str
    language: str | None = None
    style: str | None = None
    rate: str | None = None
    pitch: str | None = None
    temperature: float | None = None
    instructions: str | None = None
    volume: str | None = None

    @property
    def family(self) -> str | None:
        """The Azure Speech voice family; None for the openai engine."""
        return voice_family(self.voice) if self.engine == SPEECH else None

    def with_overrides(
        self,
        *,
        voice: str | None = None,
        language: str | None = None,
        instructions: str | None = None,
        style: str | None = None,
        rate: str | None = None,
        pitch: str | None = None,
        volume: str | None = None,
        temperature: float | None = None,
    ) -> "Profile":
        """The profile with command-line overrides applied (None keeps a value), checked again."""
        changes = {
            key: value
            for key, value in (
                ("voice", voice),
                ("language", language),
                ("instructions", instructions),
                ("style", style),
                ("rate", rate),
                ("pitch", pitch),
                ("volume", volume),
                ("temperature", temperature),
            )
            if value is not None
        }
        if not changes:
            return self
        profile = replace(self, **changes)
        validate(profile)
        return profile

    def settings(self) -> dict[str, str | float]:
        """The optional settings the profile sets, by name (as in foundry-tts.toml)."""
        return {
            key: value for key in OPTIONAL_SETTINGS if (value := getattr(self, key)) is not None
        }

    def describe(self) -> str:
        """One line for --list-profiles."""
        details = [f"{key}={value}" for key, value in self.settings().items()]
        return "  ".join([self.name, self.engine, self.voice, *details])

    def to_dict(self) -> dict:
        """The profile and what its voice supports, for scripts (profile list --json)."""
        return {
            "name": self.name,
            "engine": self.engine,
            "voice": self.voice,
            "family": self.family,
            "settings": self.settings(),
            "applies": sorted(_OPENAI_ONLY if self.engine == OPENAI else _speech_settings(self)),
        }


def voice_family(voice: str) -> str:
    name = voice.lower()
    if ":mai-voice" in name:
        return MAI_VOICE
    if ":dragonhdomni" in name:
        return DRAGON_HD_OMNI
    if ":dragonhd" in name:
        return DRAGON_HD
    return STANDARD


def _speech_settings(profile: Profile) -> set[str]:
    """The settings a speech profile's voice family accepts."""
    applies = set(_SPEECH_ONLY)
    if profile.family not in _TEMPERATURE_FAMILIES:
        applies.discard("temperature")
    return applies


def honors_break(profile: Profile) -> bool:
    return profile.family in _BREAK_FAMILIES


def _check_range(where: str, key: str, value: str, limits: tuple, form: str) -> None:
    """A plain number (a rate multiplier, an absolute volume) must be in its documented range."""
    if _PLAIN_NUMBER.match(value):
        low, high = limits
        if not low <= float(value) <= high:
            raise TtsError(f"{where}: {key} {form} must be between {low:g} and {high:g}.")


def validate(profile: Profile) -> None:
    """Refuses a profile that sets something its engine or voice family doesn't support."""
    where = f"Profile '{profile.name}'"
    if profile.engine not in ENGINES:
        raise TtsError(f"{where}: engine must be one of {', '.join(ENGINES)}.")
    if not profile.voice.strip():
        raise TtsError(f"{where}: voice is empty.")
    other_only = _SPEECH_ONLY if profile.engine == OPENAI else _OPENAI_ONLY
    for key in other_only:
        if getattr(profile, key) is not None:
            raise TtsError(f"{where}: {key} doesn't apply to the {profile.engine} engine.")
    if profile.rate is not None:
        if not _RATE.match(profile.rate):
            raise TtsError(
                f"{where}: rate '{profile.rate}' isn't a value like 1.2, -5%, +10% or slow."
            )
        _check_range(where, "rate", profile.rate, RATE_MULTIPLIER_RANGE, "as a multiplier")
    if profile.pitch is not None and not _PITCH.match(profile.pitch):
        raise TtsError(f"{where}: pitch '{profile.pitch}' isn't a value like +2st, -5% or low.")
    if profile.volume is not None:
        if not _VOLUME.match(profile.volume):
            raise TtsError(
                f"{where}: volume '{profile.volume}' isn't a value like 80, -10, +5% or soft."
            )
        _check_range(where, "volume", profile.volume, VOLUME_RANGE, "as an absolute value")
    if profile.temperature is not None:
        low, high = TEMPERATURE_RANGE
        if profile.family not in _TEMPERATURE_FAMILIES:
            raise TtsError(
                f"{where}: temperature applies to HD voices only ({DRAGON_HD}, "
                f"{DRAGON_HD_OMNI}); {profile.voice} is a {profile.family} voice."
            )
        if not low <= profile.temperature <= high:
            raise TtsError(f"{where}: temperature must be between {low} and {high}.")
