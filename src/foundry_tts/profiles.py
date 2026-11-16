"""Voice profiles: named voice settings, checked against what their voice family supports.

What each Azure Speech voice family honors was measured against the service on 2026-11-11
(eastus2) by comparing audio lengths, not only taken from the docs, which disagree with it:

| Family         | <break> | <prosody rate> | <sub> | temperature |
|----------------|---------|----------------|-------|-------------|
| Dragon HD      | yes     | yes            | yes   | yes         |
| Dragon HD Omni | yes     | yes            | yes   | yes         |
| MAI-Voice      | ignored | yes            | yes   | not defined |
| standard       | yes     | yes            | yes   | not defined |

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

# <prosody> values: a relative change ("-5%", "+2st", "+10Hz") or a named level.
_RELATIVE = r"[+-]?\d+(\.\d+)?"
_RATE = re.compile(rf"^({_RELATIVE}%|x-slow|slow|medium|fast|x-fast|default)$")
_PITCH = re.compile(rf"^({_RELATIVE}(%|st|Hz)|x-low|low|medium|high|x-high|default)$")

_SPEECH_ONLY = ("language", "style", "rate", "pitch", "temperature")
_OPENAI_ONLY = ("instructions",)


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

    @property
    def family(self) -> str | None:
        """The Azure Speech voice family; None for the openai engine."""
        return voice_family(self.voice) if self.engine == SPEECH else None

    def with_overrides(
        self, *, voice: str | None, language: str | None, instructions: str | None
    ) -> "Profile":
        """The profile with command-line overrides applied, checked again."""
        changes = {
            key: value
            for key, value in (
                ("voice", voice),
                ("language", language),
                ("instructions", instructions),
            )
            if value is not None
        }
        if not changes:
            return self
        profile = replace(self, **changes)
        validate(profile)
        return profile

    def describe(self) -> str:
        """One line for --list-profiles."""
        details = [
            f"{key}={value}"
            for key in ("language", "style", "rate", "pitch", "temperature", "instructions")
            if (value := getattr(self, key)) is not None
        ]
        return "  ".join([self.name, self.engine, self.voice, *details])


def voice_family(voice: str) -> str:
    name = voice.lower()
    if ":mai-voice" in name:
        return MAI_VOICE
    if ":dragonhdomni" in name:
        return DRAGON_HD_OMNI
    if ":dragonhd" in name:
        return DRAGON_HD
    return STANDARD


def honors_break(profile: Profile) -> bool:
    return profile.family in _BREAK_FAMILIES


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
    if profile.rate is not None and not _RATE.match(profile.rate):
        raise TtsError(f"{where}: rate '{profile.rate}' isn't a value like -5%, +10% or slow.")
    if profile.pitch is not None and not _PITCH.match(profile.pitch):
        raise TtsError(f"{where}: pitch '{profile.pitch}' isn't a value like +2st, -5% or low.")
    if profile.temperature is not None:
        low, high = TEMPERATURE_RANGE
        if profile.family not in _TEMPERATURE_FAMILIES:
            raise TtsError(
                f"{where}: temperature applies to HD voices only ({DRAGON_HD}, "
                f"{DRAGON_HD_OMNI}); {profile.voice} is a {profile.family} voice."
            )
        if not low <= profile.temperature <= high:
            raise TtsError(f"{where}: temperature must be between {low} and {high}.")
