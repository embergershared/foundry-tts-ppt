"""Text to requests to audio for one profile, splitting text that is too long for one request.

`prepare` builds every request body first (the SSML, or the gpt-4o-mini-tts JSON), so a run can
check everything before calling Azure and hash exactly what is sent. `send` posts them and joins
the parts.
"""

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from foundry_tts import engines, markup
from foundry_tts.config import Settings
from foundry_tts.errors import TtsError
from foundry_tts.markup import Lexicon, Paragraph, Pause
from foundry_tts.profiles import SPEECH, Profile
from foundry_tts.ssml import build_ssml

MP3 = ".mp3"
# Where a long paragraph may be cut: after the end of a sentence.
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
_NO_LEXICON = Lexicon({})
# ID3v2 tag: "ID3", version (2 bytes), flags (1 byte), size (4 bytes of 7 bits each).
_ID3_HEADER_BYTES = 10
_ID3_VERSION = 3
_ID3_VERSIONS = (2, 3, 4)
_ID3_SIZE = slice(6, 10)
_SYNCSAFE_BITS = 7


@dataclass(frozen=True)
class Requests:
    """The bodies to send for one text, in order, and the audio file extension."""

    profile: Profile
    bodies: list[str]
    extension: str

    @property
    def hash(self) -> str:
        """sha256 of what is sent: changes with the notes, profile, lexicon or settings."""
        digest = hashlib.sha256("\n".join(self.bodies).encode("utf-8")).hexdigest()
        return f"sha256:{digest}"


def extension(profile: Profile, settings: Settings) -> str:
    if profile.engine == SPEECH:
        return engines.speech_extension(settings.speech.output_format)
    return engines.openai_extension(settings.openai.response_format)


def split(
    paragraphs: list[Paragraph], limit: int, measure: Callable[[list[Paragraph]], int]
) -> list[list[Paragraph]]:
    """Groups of paragraphs that each measure at most `limit`, cut between paragraphs.

    A paragraph longer than the limit is cut between sentences (its parts then get a paragraph
    pause between them); a sentence longer than the limit is refused.
    """
    pieces: list[Paragraph] = []
    for paragraph in paragraphs:
        if measure([paragraph]) <= limit:
            pieces.append(paragraph)
        else:
            pieces.extend(_split_paragraph(paragraph, limit, measure))
    groups: list[list[Paragraph]] = []
    current: list[Paragraph] = []
    for piece in pieces:
        if current and measure([*current, piece]) > limit:
            groups.append(current)
            current = []
        current.append(piece)
    if current:
        groups.append(current)
    return groups


def _split_paragraph(
    paragraph: Paragraph, limit: int, measure: Callable[[list[Paragraph]], int]
) -> list[Paragraph]:
    units: Paragraph = []
    for segment in paragraph:
        if isinstance(segment, Pause):
            units.append(segment)
        else:
            units.extend(sentence for sentence in _SENTENCE_END.split(segment) if sentence)
    pieces: list[Paragraph] = []
    current: Paragraph = []
    for unit in units:
        if isinstance(unit, str) and measure([[unit]]) > limit:
            raise TtsError(
                f"A sentence has {measure([[unit]])} characters, more than the {limit} one "
                f"request takes: split it. It starts with: {unit[:60]!r}"
            )
        if current and measure([[*current, unit]]) > limit:
            pieces.append(current)
            current = []
        current.append(unit)
    if current:
        pieces.append(current)
    return pieces


def prepare(
    paragraphs: list[Paragraph], *, profile: Profile, settings: Settings, lexicon: Lexicon
) -> Requests:
    """The request bodies for the text, split to fit the engine's limit."""
    ext = extension(profile, settings)
    if profile.engine == SPEECH:
        groups = split(
            paragraphs,
            settings.speech.max_chars_per_request,
            lambda group: len(markup.to_plain_text(group, _NO_LEXICON)),
        )
        bodies = [
            build_ssml(
                group,
                profile=profile,
                language=settings.speech.language,
                paragraph_break_ms=settings.speech.paragraph_break_ms,
                lexicon=lexicon,
            )
            for group in groups
        ]
    else:
        groups = split(
            paragraphs,
            settings.openai.max_input_chars,
            lambda group: len(markup.to_plain_text(group, lexicon)),
        )
        bodies = [
            engines.openai_body(
                markup.to_plain_text(group, lexicon),
                voice=profile.voice,
                instructions=profile.instructions or "",
                settings=settings,
            )
            for group in groups
        ]
    if len(bodies) > 1 and ext != MP3:
        raise TtsError(
            f"The text is too long for one request, and only MP3 parts can be joined; "
            f"'{profile.name}' makes {ext} audio. Use an MP3 format or shorten the text."
        )
    return Requests(profile=profile, bodies=bodies, extension=ext)


def send(
    requests: Requests,
    *,
    settings: Settings,
    client: httpx.Client,
    get_token: engines.TokenProvider,
) -> bytes:
    """Posts each body and returns the audio, the parts joined when there are several."""
    parts = []
    for body in requests.bodies:
        if requests.profile.engine == SPEECH:
            parts.append(engines.synthesize_speech(body, settings, client, get_token))
        else:
            parts.append(engines.synthesize_openai_body(body, settings, client, get_token))
    return join_mp3(parts)


def _without_id3(audio: bytes) -> bytes:
    """The audio without a leading ID3v2 tag; unchanged when it doesn't start with a valid one."""
    if len(audio) < _ID3_HEADER_BYTES or not audio.startswith(b"ID3"):
        return audio
    size_bytes = audio[_ID3_SIZE]
    if audio[_ID3_VERSION] not in _ID3_VERSIONS or any(b >> _SYNCSAFE_BITS for b in size_bytes):
        return audio
    size = 0
    for byte in size_bytes:
        size = (size << _SYNCSAFE_BITS) | byte
    return audio[_ID3_HEADER_BYTES + size :]


def join_mp3(parts: list[bytes]) -> bytes:
    """MP3 parts played one after the other: the frames joined, tags after the first removed."""
    return parts[0] + b"".join(_without_id3(part) for part in parts[1:])
