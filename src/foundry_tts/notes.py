"""Cleanups for speaker notes, which are written for a presenter rather than for the ear.

Applied to deck notes before the markup is parsed (see markup.py), in this order:

| Cleanup  | Before               | After                     |
|----------|----------------------|---------------------------|
| `cue`    | `(Click)`            | `[pause 500ms]` (`[deck] cue_pause_ms`) |
| `emoji`  | `Great news 🎉`      | `Great news`              |
| `bullet` | `- item`, `• item`   | `item`, as its own paragraph |
| `quote`  | `“so-called” "tool"` | `so-called tool`          |
| `range`  | `10–15`              | `10 to 15`                |
| `space`  | `the end .`          | `the end.`                |

Each one is counted, so the log can say what changed on which slide.
"""

import re
from dataclasses import dataclass, field

# A "(Click)" cue for the presenter: becomes a pause instead of being read out.
_CUE = re.compile(r"\(\s*click\s*\)", re.IGNORECASE)
# Emoji, as code point ranges: pictographs, miscellaneous symbols and dingbats, arrows and
# stars, flags; plus the characters emoji are built with (variation selector 16, zero-width
# joiner, combining keycap).
_EMOJI_RANGES = ((0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2B00, 0x2BFF), (0x1F1E6, 0x1F1FF))
_EMOJI_PARTS = (0xFE0F, 0x200D, 0x20E3)
_EMOJI = re.compile(
    "["
    + "".join(f"{chr(first)}-{chr(last)}" for first, last in _EMOJI_RANGES)
    + "".join(chr(part) for part in _EMOJI_PARTS)
    + "]+"
)
# A bullet at the start of a line (CR, LF and the vertical tab of PowerPoint line breaks).
_BULLET = re.compile(r"(^|[\r\n\v])[ \t]*[-–•▪◦‣·*][ \t]+")
# Double quotes carry nothing to say; apostrophes and single quotes are kept.
_QUOTE = re.compile('["“”„«»]')
# A number range with an en dash or em dash: 10–15, 5%–10%, $10–$15.
_RANGE = re.compile(r"(\d%?)[ \t]*[–—][ \t]*([$€£]?\d)")
# Spaces before punctuation, left behind by the cleanups above or typed by the presenter.
_SPACE = re.compile(r"[ \t]+([.,;:!?])")


@dataclass(frozen=True)
class Cleaned:
    text: str
    counts: dict[str, int] = field(default_factory=dict)


def clean(text: str, *, cue_pause_ms: int) -> Cleaned:
    """The notes with presenter cues, emoji, bullets and quotes removed and ranges read out."""
    counts: dict[str, int] = {}

    def apply(name: str, pattern: re.Pattern, replacement, value: str) -> str:
        result, count = pattern.subn(replacement, value)
        if count:
            counts[name] = count
        return result

    text = apply("cue", _CUE, f" [pause {cue_pause_ms}ms] ", text)
    text = apply("emoji", _EMOJI, "", text)
    # Each bullet becomes its own paragraph, so the voice pauses between the items of a list.
    text = apply("bullet", _BULLET, lambda match: "\n" if match[1] else "", text)
    text = apply("quote", _QUOTE, "", text)
    text = apply("range", _RANGE, r"\1 to \2", text)
    text = apply("space", _SPACE, r"\1", text)
    return Cleaned(text, counts)
