"""Builds the SSML sent to Azure Speech from parsed text and a voice profile."""

import logging
from xml.sax.saxutils import quoteattr

from foundry_tts.markup import Lexicon, Paragraph, Pause, has_pauses
from foundry_tts.profiles import Profile, honors_break

log = logging.getLogger(__name__)

SSML_NAMESPACE = "http://www.w3.org/2001/10/synthesis"
MSTTS_NAMESPACE = "http://www.w3.org/2001/mstts"


def _break(ms: int) -> str:
    return f'<break time="{ms}ms"/>'


def build_ssml(
    paragraphs: list[Paragraph],
    *,
    profile: Profile,
    language: str,
    paragraph_break_ms: int,
    lexicon: Lexicon,
) -> str:
    """SSML for the paragraphs, read with the profile's voice, style, prosody and temperature.

    Voices that ignore <break> (MAI-Voice) get no pauses at all; a pause asked for in the text is
    then reported as a warning rather than sent and silently dropped.
    """
    breaks = honors_break(profile)
    if not breaks and has_pauses(paragraphs):
        log.warning(
            "This voice ignores pauses: the [pause] markup is left out.",
            extra={"profile": profile.name, "voice": profile.voice, "family": profile.family},
        )

    rendered = []
    for paragraph in paragraphs:
        parts = []
        for segment in paragraph:
            if isinstance(segment, Pause):
                if breaks:
                    parts.append(_break(segment.ms))
            else:
                parts.append(lexicon.to_ssml(segment))
        if parts:
            rendered.append(" ".join(parts))
    separator = f" {_break(paragraph_break_ms)} " if breaks else " "
    body = separator.join(rendered)

    if profile.rate is not None or profile.pitch is not None:
        attributes = "".join(
            f" {name}={quoteattr(value)}"
            for name, value in (("rate", profile.rate), ("pitch", profile.pitch))
            if value is not None
        )
        body = f"<prosody{attributes}>{body}</prosody>"
    if profile.style is not None:
        body = f"<mstts:express-as style={quoteattr(profile.style)}>{body}</mstts:express-as>"
    parameters = (
        f" parameters={quoteattr(f'temperature={profile.temperature}')}"
        if profile.temperature is not None
        else ""
    )
    return (
        f'<speak version="1.0" xmlns="{SSML_NAMESPACE}" xmlns:mstts="{MSTTS_NAMESPACE}" '
        f"xml:lang={quoteattr(profile.language or language)}>"
        f"<voice name={quoteattr(profile.voice)}{parameters}>{body}</voice></speak>"
    )
