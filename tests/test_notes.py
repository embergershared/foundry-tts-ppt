import pytest

from foundry_tts import notes

ROCKET = chr(0x1F680)
CHECK = chr(0x2705) + chr(0xFE0F)  # with variation selector 16
FAMILY = chr(0x1F468) + chr(0x200D) + chr(0x1F469)  # joined by a zero-width joiner
BULLET = chr(0x2022)
EN_DASH, EM_DASH = chr(0x2013), chr(0x2014)
LEFT_QUOTE, RIGHT_QUOTE = chr(0x201C), chr(0x201D)


def clean(text: str) -> notes.Cleaned:
    return notes.clean(text, cue_pause_ms=500)


@pytest.mark.parametrize(
    ("before", "after", "counts"),
    [
        ("Next (Click) slide", "Next  [pause 500ms]  slide", {"cue": 1}),
        ("(click)(CLICK)( Click )", " [pause 500ms]  [pause 500ms]  [pause 500ms] ", {"cue": 3}),
        (f"Launch {ROCKET}{CHECK} {FAMILY}!", "Launch!", {"emoji": 2, "space": 1}),
        (f"- one\n{BULLET} two\v* three", "one\ntwo\nthree", {"bullet": 3}),
        (f'{LEFT_QUOTE}So-called{RIGHT_QUOTE} "tools"', "So-called tools", {"quote": 4}),
        (f"10{EN_DASH}15, 5% {EM_DASH} 10%, $10{EN_DASH}$15", "10 to 15, 5% to 10%, $10 to $15",
         {"range": 3}),
        ("The end .", "The end.", {"space": 1}),
    ],
)  # fmt: skip
def test_each_cleanup(before, after, counts):
    assert clean(before) == notes.Cleaned(after, counts)


@pytest.mark.parametrize(
    "text",
    [
        "Wi-Fi and a -5% rate",  # a hyphen inside a word or before a number
        "It's the team's plan",  # apostrophes
        "2027-2028 budget",  # a hyphen range is left to the voice
        "Click the button",  # "click" outside parentheses
        "A - B",  # a dash in the middle of a line
    ],
)
def test_text_that_is_kept(text):
    assert clean(text) == notes.Cleaned(text, {})


def test_cue_pause_length_comes_from_the_settings():
    assert notes.clean("(Click)", cue_pause_ms=1200).text == " [pause 1200ms] "
