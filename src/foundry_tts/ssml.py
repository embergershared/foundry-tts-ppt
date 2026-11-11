"""Builds the SSML sent to Azure Speech from plain text."""

import re
from xml.sax.saxutils import escape, quoteattr

from foundry_tts.errors import TtsError

SSML_NAMESPACE = "http://www.w3.org/2001/10/synthesis"
MSTTS_NAMESPACE = "http://www.w3.org/2001/mstts"

# PowerPoint notes separate paragraphs with CR and use a vertical tab (\v) for a line break
# inside a paragraph; text files use LF or CRLF.
_PARAGRAPH_SPLIT = re.compile(r"[\r\n]+")
_LINE_BREAK = re.compile(r"[\v\t ]+")


def split_paragraphs(text: str) -> list[str]:
    """Non-empty paragraphs, with inner whitespace and line breaks collapsed to one space."""
    paragraphs = (_LINE_BREAK.sub(" ", part).strip() for part in _PARAGRAPH_SPLIT.split(text))
    return [paragraph for paragraph in paragraphs if paragraph]


def build_ssml(text: str, *, voice: str, language: str, paragraph_break_ms: int) -> str:
    """SSML for `text` read by `voice`: each paragraph escaped, a pause between paragraphs."""
    paragraphs = split_paragraphs(text)
    if not paragraphs:
        raise TtsError("The text is empty; there is nothing to say.")
    pause = f' <break time="{paragraph_break_ms}ms"/> '
    body = pause.join(escape(paragraph) for paragraph in paragraphs)
    return (
        f'<speak version="1.0" xmlns="{SSML_NAMESPACE}" xmlns:mstts="{MSTTS_NAMESPACE}" '
        f"xml:lang={quoteattr(language)}><voice name={quoteattr(voice)}>{body}</voice></speak>"
    )
