import pytest

from foundry_tts.errors import TtsError
from foundry_tts.markup import MAX_PAUSE_MS, Lexicon, Pause, has_pauses, parse, to_plain_text


def test_paragraphs_split_on_cr_lf_and_crlf_and_join_vertical_tab_lines():
    text = "First line\vsame paragraph\r\nSecond\rThird\n\n  \nFourth"
    assert parse(text) == [["First line same paragraph"], ["Second"], ["Third"], ["Fourth"]]


def test_comment_lines_are_not_spoken_even_inside_a_notes_paragraph():
    text = "// remember to smile\nHello all.\vNice to see you.\v  // slow down here\nBye."
    assert parse(text) == [["Hello all. Nice to see you."], ["Bye."]]


def test_a_url_with_double_slash_inside_a_line_is_kept():
    assert parse("See https://contoso.com today.") == [["See https://contoso.com today."]]


@pytest.mark.parametrize(
    ("markup", "ms"),
    [
        ("[pause 1s]", 1000),
        ("[pause 750ms]", 750),
        ("[Pause 1.5 s]", 1500),
        ("[PAUSE 0.25s]", 250),
    ],
)
def test_pause_markup(markup, ms):
    assert parse(f"Before {markup} after.") == [["Before", Pause(ms), "after."]]


def test_pause_at_the_edges_and_other_brackets_kept_as_text():
    assert parse("[pause 1s] [excited] Great news! [pause 2s]") == [
        [Pause(1000), "[excited] Great news!", Pause(2000)]
    ]


def test_a_pause_longer_than_azure_takes_is_refused():
    assert parse(f"a [pause {MAX_PAUSE_MS}ms] b")[0][1] == Pause(MAX_PAUSE_MS)
    with pytest.raises(TtsError, match="at most 20 s"):
        parse("a [pause 21s] b")


@pytest.mark.parametrize("text", [" \n\v ", "// only a comment", "[pause 1s]\n// note"])
def test_nothing_to_say_is_refused(text):
    with pytest.raises(TtsError, match="nothing to say"):
        parse(text)


def test_has_pauses():
    assert has_pauses(parse("a [pause 1s] b"))
    assert not has_pauses(parse("a b"))


def test_lexicon_wraps_whole_words_only_and_escapes():
    lexicon = Lexicon({"AKS": "A K S", "Q&A": "Q and A", "AKS-HCI": "A K S H C I"})
    ssml = lexicon.to_ssml("AKS & AKS-HCI <now>, not MAKS or aks. Q&A")
    assert ssml == (
        '<sub alias="A K S">AKS</sub> &amp; <sub alias="A K S H C I">AKS-HCI</sub> &lt;now&gt;, '
        'not MAKS or aks. <sub alias="Q and A">Q&amp;A</sub>'
    )


def test_lexicon_alias_with_quotes_stays_valid_xml():
    assert Lexicon({"X": 'say "ex"'}).to_ssml("X") == "<sub alias='say \"ex\"'>X</sub>"


def test_lexicon_plain_text_replaces_words():
    assert Lexicon({"SaaS": "sass"}).to_plain("Our SaaS, SaaSy.") == "Our sass, SaaSy."


def test_empty_lexicon_only_escapes():
    assert Lexicon({}).to_ssml("a & b") == "a &amp; b"
    assert Lexicon({}).to_plain("a & b") == "a & b"


def test_plain_text_for_openai_has_ellipsis_pauses_and_blank_lines():
    paragraphs = parse("Hello AKS. [pause 1s] Next.\n// hidden\nSecond paragraph.")
    assert to_plain_text(paragraphs, Lexicon({"AKS": "A K S"})) == (
        "Hello A K S. ... Next.\n\nSecond paragraph."
    )
