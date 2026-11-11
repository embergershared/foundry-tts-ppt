"""Light markup a presenter can type in plain text or speaker notes, and the pronunciation list.

- A line starting with `//` is a comment to yourself: it isn't spoken.
- `[pause 1s]`, `[pause 750ms]`, `[pause 1.5s]`: a pause of that length.
- Anything else in square brackets is left as is (HD voices read `[excited]` as a style tag).

The lexicon maps a word or acronym to how it is said (whole words, case-sensitive).
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from xml.sax.saxutils import escape, quoteattr

from foundry_tts.errors import TtsError

# Longest pause Azure Speech accepts in <break time>; longer values are cut to it.
# https://learn.microsoft.com/azure/ai-services/speech-service/speech-synthesis-markup-structure#add-a-break
MAX_PAUSE_MS = 20000
MS_PER_SECOND = 1000
COMMENT_PREFIX = "//"
# What a pause becomes for the openai engine, which takes plain text only.
PLAIN_PAUSE = " ... "

# PowerPoint notes separate paragraphs with CR and use a vertical tab (\v) for a line break
# inside a paragraph; text files use LF or CRLF.
_PARAGRAPH_SPLIT = re.compile(r"[\r\n]+")
_SPACES = re.compile(r"[\t ]+")
_PAUSE = re.compile(r"\[pause\s+(\d+(?:\.\d+)?)\s*(ms|s)\]", re.IGNORECASE)


@dataclass(frozen=True)
class Pause:
    ms: int


Segment = str | Pause
Paragraph = list[Segment]


def _pause_ms(amount: str, unit: str) -> int:
    value = float(amount) * (MS_PER_SECOND if unit.lower() == "s" else 1)
    ms = round(value)
    if ms > MAX_PAUSE_MS:
        raise TtsError(
            f"[pause {amount}{unit}] is too long: Azure Speech takes at most "
            f"{MAX_PAUSE_MS // MS_PER_SECOND} s. Split it into several pauses."
        )
    return ms


def _segments(text: str) -> Paragraph:
    segments: Paragraph = []
    position = 0
    for match in _PAUSE.finditer(text):
        before = text[position : match.start()].strip()
        if before:
            segments.append(before)
        segments.append(Pause(_pause_ms(match[1], match[2])))
        position = match.end()
    rest = text[position:].strip()
    if rest:
        segments.append(rest)
    return segments


def parse(text: str, *, allow_empty: bool = False) -> list[Paragraph]:
    """Paragraphs of text and pauses, with comment lines removed and spaces collapsed.

    Text with nothing to say (empty, or only comments and pauses) is refused, or gives an empty
    list with `allow_empty` (speaker notes that are only comments).
    """
    paragraphs = []
    for block in _PARAGRAPH_SPLIT.split(text):
        lines = (line.strip() for line in block.split("\v"))
        kept = [line for line in lines if line and not line.startswith(COMMENT_PREFIX)]
        segments = _segments(_SPACES.sub(" ", " ".join(kept)))
        if segments:
            paragraphs.append(segments)
    if not any(isinstance(segment, str) for paragraph in paragraphs for segment in paragraph):
        if allow_empty:
            return []
        raise TtsError("The text is empty (or only comments and pauses); there is nothing to say.")
    return paragraphs


def has_pauses(paragraphs: list[Paragraph]) -> bool:
    return any(isinstance(segment, Pause) for paragraph in paragraphs for segment in paragraph)


class Lexicon:
    """Whole-word, case-sensitive replacements; the longest entry wins when entries overlap."""

    def __init__(self, entries: Mapping[str, str]):
        self.entries = dict(entries)
        words = sorted(self.entries, key=len, reverse=True)
        alternatives = "|".join(re.escape(word) for word in words)
        self._pattern = re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)") if words else None

    def to_ssml(self, text: str) -> str:
        """Escaped text, each listed word wrapped in <sub alias="…">."""
        if self._pattern is None:
            return escape(text)
        parts = []
        position = 0
        for match in self._pattern.finditer(text):
            word = match[0]
            parts.append(escape(text[position : match.start()]))
            parts.append(f"<sub alias={quoteattr(self.entries[word])}>{escape(word)}</sub>")
            position = match.end()
        parts.append(escape(text[position:]))
        return "".join(parts)

    def to_plain(self, text: str) -> str:
        if self._pattern is None:
            return text
        return self._pattern.sub(lambda match: self.entries[match[0]], text)


def to_plain_text(paragraphs: list[Paragraph], lexicon: Lexicon) -> str:
    """Plain text for the openai engine: pauses become an ellipsis, paragraphs a blank line."""
    rendered = []
    for paragraph in paragraphs:
        parts = [
            PLAIN_PAUSE if isinstance(segment, Pause) else lexicon.to_plain(segment)
            for segment in paragraph
        ]
        rendered.append(" ".join(part.strip() for part in parts).strip())
    return "\n\n".join(paragraph for paragraph in rendered if paragraph)
