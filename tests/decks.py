"""A synthetic Contoso deck with the quirks of real speaker notes (no real content).

It copies what a real sample deck showed (docs/plan.md, "What a real sample deck shows"): line
breaks inside a paragraph (a vertical tab), empty paragraphs, "(Click)" cues, an emoji, "- "
bullets, stray quotes, a space before a full stop, acronyms with "&", an en-dash range and an
email address. It adds what that deck lacks: a slide without notes, a hidden slide, and a slide
whose notes are only a comment.
"""

from pathlib import Path

from pptx import Presentation

WAVE = chr(0x1F44B)
EN_DASH = chr(0x2013)
LEFT_QUOTE, RIGHT_QUOTE = chr(0x201C), chr(0x201D)
LINE_BREAK = "\v"  # python-pptx writes <a:br/> for it; PowerPoint reads it back as char 11

SLIDE_1_NOTES = (
    f"Welcome to the Contoso cloud roadmap for 2027. {WAVE}\n"
    "\n"
    f"(Click) Today we cover three topics:{LINE_BREAK}- the release plan{LINE_BREAK}"
    f"- the AKS platform and R&D{LINE_BREAK}- Q&A at the end ."
)
SLIDE_4_NOTES = (
    "// Check the dates with Fabrikam before the meeting.\n"
    f"The migration runs November 10{EN_DASH}15. Send questions to cloud@contoso.com.\n"
    f'{LEFT_QUOTE}Zero downtime{RIGHT_QUOTE} is the goal. (Click) "Thank you."'
)

# (title, notes or None for no notes slide, hidden)
CONTOSO_SLIDES = [
    ("Contoso cloud roadmap 2027", SLIDE_1_NOTES, False),
    ("Agenda", None, False),
    ("Backup: rates", "These rates are for the backup slide only.", True),
    ("Migration", SLIDE_4_NOTES, False),
    ("Thank you", "// Nothing to say here.", False),
]
TITLE_ONLY_LAYOUT = 5


def make_deck(path: Path, slides=CONTOSO_SLIDES) -> Path:
    presentation = Presentation()
    layout = presentation.slide_layouts[TITLE_ONLY_LAYOUT]
    for title, notes, hidden in slides:
        slide = presentation.slides.add_slide(layout)
        slide.shapes.title.text = title
        if notes is not None:
            slide.notes_slide.notes_text_frame.text = notes
        if hidden:
            slide._element.set("show", "0")
    presentation.save(str(path))
    return path
