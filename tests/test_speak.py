import hashlib
import json
from dataclasses import replace

import pytest
from conftest import FAKE_AUDIO

from foundry_tts import markup, speak
from foundry_tts.errors import TtsError
from foundry_tts.markup import Lexicon, Pause

NO_LEXICON = Lexicon({})


def length(group):
    return len(markup.to_plain_text(group, NO_LEXICON))


def with_limits(settings, *, speech=None, openai=None, output_format=None):
    return replace(
        settings,
        speech=replace(
            settings.speech,
            max_chars_per_request=speech or settings.speech.max_chars_per_request,
            output_format=output_format or settings.speech.output_format,
        ),
        openai=replace(settings.openai, max_input_chars=openai or settings.openai.max_input_chars),
    )


def test_split_groups_whole_paragraphs():
    paragraphs = markup.parse("aaaa\nbbbb\ncccc")
    # "aaaa\n\nbbbb" is 10 characters: two paragraphs fit, the third starts a new group.
    assert speak.split(paragraphs, 10, length) == [[["aaaa"], ["bbbb"]], [["cccc"]]]


def test_split_cuts_a_long_paragraph_between_sentences():
    paragraphs = markup.parse("One two. Three four! Five six? Seven.")
    groups = speak.split(paragraphs, 20, length)
    assert [length(group) for group in groups] == [20, 16]
    assert groups[0] == [["One two.", "Three four!"]]


def test_split_keeps_pauses_with_their_sentence():
    paragraphs = markup.parse("One two. [pause 1s] Three four.")
    # "One two. ..." is 12 characters.
    assert speak.split(paragraphs, 12, length) == [[["One two.", Pause(1000)]], [["Three four."]]]


def test_a_sentence_longer_than_the_limit_is_refused():
    with pytest.raises(TtsError, match="A sentence has 24 characters, more than the 10"):
        speak.split(markup.parse("This sentence is longer."), 10, length)


def test_prepare_speech_splits_into_several_ssml_bodies(settings):
    small = with_limits(settings, speech=20)
    requests = speak.prepare(
        markup.parse("First paragraph.\nSecond paragraph."),
        profile=small.profile("ava-hd"),
        settings=small,
        lexicon=NO_LEXICON,
    )
    assert len(requests.bodies) == 2
    assert all(body.startswith("<speak") for body in requests.bodies)
    assert "First paragraph." in requests.bodies[0]
    assert "Second paragraph." in requests.bodies[1]
    assert requests.extension == ".mp3"


def test_prepare_openai_measures_the_text_after_the_lexicon(settings):
    small = with_limits(settings, openai=12)
    requests = speak.prepare(
        markup.parse("AKS one.\nAKS two."),  # "A K S one." is 10 characters
        profile=small.profile("marin-presenter"),
        settings=small,
        lexicon=Lexicon({"AKS": "A K S"}),
    )
    assert [json.loads(body)["input"] for body in requests.bodies] == ["A K S one.", "A K S two."]


def test_split_parts_need_mp3(settings):
    wav = with_limits(settings, speech=10, output_format="riff-24khz-16bit-mono-pcm")
    with pytest.raises(TtsError, match="only MP3 parts can be joined"):
        speak.prepare(
            markup.parse("aaaa\nbbbb\ncccc"),
            profile=wav.profile("ava-hd"),
            settings=wav,
            lexicon=NO_LEXICON,
        )


def test_hash_is_the_sha256_of_the_bodies(settings):
    requests = speak.Requests(settings.profile("ava-hd"), ["<speak>a</speak>"], ".mp3")
    expected = hashlib.sha256(b"<speak>a</speak>").hexdigest()
    assert requests.hash == f"sha256:{expected}"


def test_hash_changes_with_the_profile(settings):
    paragraphs = markup.parse("Hello")

    def hash_of(name):
        profile = settings.profile(name)
        return speak.prepare(
            paragraphs, profile=profile, settings=settings, lexicon=NO_LEXICON
        ).hash

    assert hash_of("ava-hd") == hash_of("ava-hd")
    assert hash_of("ava-hd") != hash_of("ava-hd-steady")


def test_send_posts_each_part_and_joins_them(settings, client, transport):
    small = with_limits(settings, speech=10)
    requests = speak.prepare(
        markup.parse("aaaa\nbbbb\ncccc"),
        profile=small.profile("ava-hd"),
        settings=small,
        lexicon=NO_LEXICON,
    )
    audio = speak.send(requests, settings=small, client=client, get_token=lambda: "t")
    assert len(transport.requests) == 2
    assert [request.content.decode() for request in transport.requests] == requests.bodies
    # The fake audio starts with "ID3" but has no valid tag: kept whole in each part.
    assert audio.startswith(FAKE_AUDIO)


def id3_tag(payload_size: int) -> bytes:
    size = bytes((payload_size >> shift) & 0x7F for shift in (21, 14, 7, 0))
    return b"ID3\x04\x00\x00" + size + b"\x00" * payload_size


def test_join_mp3_drops_the_tags_of_later_parts():
    first = id3_tag(5) + b"FRAMES1"
    second = id3_tag(200) + b"FRAMES2"
    assert speak.join_mp3([first, second, b"FRAMES3"]) == first + b"FRAMES2FRAMES3"


def test_openai_body_is_sent_as_built(settings, client, transport):
    requests = speak.prepare(
        markup.parse("Bonjour, ça va ?"),
        profile=settings.profile("marin-presenter"),
        settings=settings,
        lexicon=NO_LEXICON,
    )
    speak.send(requests, settings=settings, client=client, get_token=lambda: "t")
    (request,) = transport.requests
    assert request.content.decode("utf-8") == requests.bodies[0]
    assert request.headers["Content-Type"] == "application/json"
    assert json.loads(request.content)["input"] == "Bonjour, ça va ?"
