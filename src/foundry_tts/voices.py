"""The Azure Speech voices a resource offers (`foundry-tts voice list`), read from its voice list
API and filtered by language, gender, family and a search text."""

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass

from foundry_tts.errors import TtsError
from foundry_tts.profiles import DRAGON_HD, DRAGON_HD_OMNI, MAI_VOICE, STANDARD, voice_family

FAMILIES = (DRAGON_HD, DRAGON_HD_OMNI, MAI_VOICE, STANDARD)


@dataclass(frozen=True)
class Voice:
    name: str  # what a profile's voice takes, e.g. en-US-Grant:MAI-Voice-2.1
    display_name: str
    locale: str
    locale_name: str
    gender: str
    family: str
    model: str
    status: str
    styles: tuple[str, ...]
    personalities: tuple[str, ...]
    scenarios: tuple[str, ...]

    def describe(self) -> str:
        """One line of `voice list`."""
        styles = ", ".join(self.styles) or "-"
        return (
            f"{self.name:<44} {self.gender:<7} {self.family:<14} {self.status:<8} styles: {styles}"
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def matches(self, search: str) -> bool:
        """Whether the search text is in its name, display name, styles, personalities or
        scenarios (case ignored)."""
        needle = search.casefold()
        haystack = (
            self.name,
            self.display_name,
            *self.styles,
            *self.personalities,
            *self.scenarios,
        )
        return any(needle in text.casefold() for text in haystack)


def _strings(value: object) -> tuple[str, ...]:
    return (
        tuple(item for item in value if isinstance(item, str)) if isinstance(value, list) else ()
    )


def from_api(entry: Mapping) -> Voice:
    """One entry of the voice list API."""
    name = entry.get("ShortName")
    if not isinstance(name, str) or not name:
        raise TtsError("Azure Speech returned a voice without a ShortName.")
    tags = entry.get("VoiceTag") if isinstance(entry.get("VoiceTag"), Mapping) else {}
    models = _strings(tags.get("ModelSeries"))
    return Voice(
        name=name,
        display_name=str(entry.get("DisplayName") or name),
        locale=str(entry.get("Locale") or ""),
        locale_name=str(entry.get("LocaleName") or ""),
        gender=str(entry.get("Gender") or ""),
        family=voice_family(name),
        model=models[0] if models else "",
        status=str(entry.get("Status") or ""),
        styles=_strings(entry.get("StyleList")),
        personalities=_strings(tags.get("VoicePersonalities")),
        scenarios=_strings(tags.get("TailoredScenarios")),
    )


def parse(entries: Iterable[Mapping]) -> list[Voice]:
    """The voices of the voice list API's answer, sorted by language, then name."""
    voices = [from_api(entry) for entry in entries if isinstance(entry, Mapping)]
    return sorted(voices, key=lambda voice: (voice.locale.casefold(), voice.name.casefold()))


def select(
    voices: Iterable[Voice],
    *,
    language: str | None = None,
    gender: str | None = None,
    family: str | None = None,
    search: str | None = None,
) -> list[Voice]:
    """The voices that pass every filter given. A language is a locale (en-US) or a language
    (en: every en-* locale); case is ignored throughout."""
    selected = []
    for voice in voices:
        locale = voice.locale.casefold()
        if language:
            wanted = language.casefold()
            if locale != wanted and not locale.startswith(f"{wanted}-"):
                continue
        if gender and voice.gender.casefold() != gender.casefold():
            continue
        if family and voice.family.casefold() != family.casefold():
            continue
        if search and not voice.matches(search):
            continue
        selected.append(voice)
    return selected
