import xml.etree.ElementTree as ET

import pytest

from foundry_tts.errors import TtsError
from foundry_tts.ssml import build_ssml, split_paragraphs

NS = "{http://www.w3.org/2001/10/synthesis}"


def test_paragraphs_split_on_cr_lf_and_crlf_and_join_vertical_tab_lines():
    text = "First line\vsame paragraph\r\nSecond\rThird\n\n  \nFourth"
    assert split_paragraphs(text) == ["First line same paragraph", "Second", "Third", "Fourth"]


def test_ssml_escapes_text_and_puts_a_break_between_paragraphs():
    ssml = build_ssml(
        'Q&A <now>\n"Done" & dusted',
        voice="en-US-Ava:DragonHDLatestNeural",
        language="en-US",
        paragraph_break_ms=400,
    )
    root = ET.fromstring(ssml)  # well-formed XML
    voice = root.find(f"{NS}voice")
    assert voice.get("name") == "en-US-Ava:DragonHDLatestNeural"
    assert root.get("{http://www.w3.org/XML/1998/namespace}lang") == "en-US"
    breaks = voice.findall(f"{NS}break")
    assert [b.get("time") for b in breaks] == ["400ms"]
    assert voice.text.strip() == "Q&A <now>"
    assert breaks[0].tail.strip() == '"Done" & dusted'


def test_voice_and_language_are_escaped_as_attributes():
    ssml = build_ssml("Hi", voice='a"b', language="en-US", paragraph_break_ms=1)
    assert ET.fromstring(ssml).find(f"{NS}voice").get("name") == 'a"b'


def test_empty_text_is_refused():
    with pytest.raises(TtsError, match="empty"):
        build_ssml(" \n\v ", voice="v", language="en-US", paragraph_break_ms=1)
