import logging
import xml.etree.ElementTree as ET

from foundry_tts.markup import Lexicon, parse
from foundry_tts.profiles import Profile
from foundry_tts.ssml import build_ssml

NS = "{http://www.w3.org/2001/10/synthesis}"
MSTTS = "{http://www.w3.org/2001/mstts}"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
HD = "en-US-Ava:DragonHDLatestNeural"
MAI = "en-US-Harper:MAI-Voice-2.1"


def build(text, lexicon=None, **profile):
    return build_ssml(
        parse(text),
        profile=Profile(name="p", engine="speech", voice=profile.pop("voice", HD), **profile),
        language="en-US",
        paragraph_break_ms=400,
        lexicon=Lexicon(lexicon or {}),
    )


def test_plain_profile_escapes_text_and_puts_a_break_between_paragraphs():
    root = ET.fromstring(build('Q&A <now>\n"Done" & dusted'))
    assert root.get(XML_LANG) == "en-US"
    voice = root.find(f"{NS}voice")
    assert voice.get("name") == HD
    assert voice.get("parameters") is None
    breaks = voice.findall(f"{NS}break")
    assert [b.get("time") for b in breaks] == ["400ms"]
    assert voice.text.strip() == "Q&A <now>"
    assert breaks[0].tail.strip() == '"Done" & dusted'


def test_pause_markup_becomes_a_break():
    voice = ET.fromstring(build("One [pause 1.5s] two")).find(f"{NS}voice")
    assert [b.get("time") for b in voice.iter(f"{NS}break")] == ["1500ms"]


def test_style_prosody_temperature_and_language_wrap_the_text():
    ssml = build(
        "Hello", style="calm", rate="-5%", pitch="+2st", temperature=0.6, language="en-GB"
    )
    root = ET.fromstring(ssml)
    assert root.get(XML_LANG) == "en-GB"
    voice = root.find(f"{NS}voice")
    assert voice.get("parameters") == "temperature=0.6"
    express = voice.find(f"{MSTTS}express-as")
    assert express.get("style") == "calm"
    prosody = express.find(f"{NS}prosody")
    assert (prosody.get("rate"), prosody.get("pitch"), prosody.text) == ("-5%", "+2st", "Hello")


def test_only_the_prosody_attributes_that_are_set():
    prosody = ET.fromstring(build("Hi", rate="slow")).find(f"{NS}voice/{NS}prosody")
    assert prosody.attrib == {"rate": "slow"}


def test_lexicon_words_become_sub_elements():
    voice = ET.fromstring(build("Run AKS now", lexicon={"AKS": "A K S"})).find(f"{NS}voice")
    sub = voice.find(f"{NS}sub")
    assert (sub.get("alias"), sub.text, voice.text, sub.tail) == ("A K S", "AKS", "Run ", " now")


def test_mai_voice_gets_no_breaks_and_a_warning_when_pauses_were_asked(caplog):
    with caplog.at_level(logging.WARNING):
        ssml = build("One [pause 1s] two\nThree", voice=MAI, style="narrator")
    assert "<break" not in ssml
    assert "One two Three" in ssml
    assert "ignores pauses" in caplog.text


def test_mai_voice_without_pause_markup_logs_nothing(caplog):
    with caplog.at_level(logging.WARNING):
        build("One\nTwo", voice=MAI)
    assert caplog.text == ""


def test_voice_and_language_are_escaped_as_attributes():
    root = ET.fromstring(build("Hi", voice='a"b', language="x'y"))
    assert root.find(f"{NS}voice").get("name") == 'a"b'
    assert root.get(XML_LANG) == "x'y"
