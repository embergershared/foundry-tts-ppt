"""Where the deck commands write, kept within PowerPoint's path limit.

PowerPoint saves and opens a file only if its full path is at most [deck] max_path_chars long,
even with Windows long paths turned on, and it cuts a longer name without an error. The deck's
name appears twice in the narrated copy's default path (output/<deck>/<deck>.narrated.pptx), so a
long one is shortened: the folder only if it has to be, then the file names. The same deck always
gets the same names, so reruns still find their earlier files.
"""

import logging
import os
from pathlib import Path

from foundry_tts.config import DeckSettings, Settings
from foundry_tts.errors import TtsError

log = logging.getLogger(__name__)

NARRATED_SUFFIX = ".narrated.pptx"
VIDEO_SUFFIX = ".narrated.mp4"
# Dropped from the end of a shortened name: Windows ignores trailing dots and spaces, and a
# dangling "-" or "_" reads as a mistake.
_TRAILING = " .-_"


def path_chars(path: Path) -> int:
    """The length of the full path, as PowerPoint gets it."""
    return len(str(path.resolve()))


def _room(folder: Path, after_name: int, limits: DeckSettings) -> int:
    """Characters left for a name in folder, when after_name more characters follow it."""
    return limits.max_path_chars - path_chars(folder) - len(os.sep) - after_name


def _shortened(name: str, room: int, limits: DeckSettings) -> str:
    """name cut to room characters, at the last space if that keeps min_name_chars."""
    cut = name[:room]
    space = cut.rfind(" ")
    if space >= limits.min_name_chars:
        cut = cut[:space]
    return cut.rstrip(_TRAILING) or name[:room]


def _too_long(folder: Path, room: int, limits: DeckSettings) -> TtsError:
    return TtsError(
        f"The folder {folder} is too long for PowerPoint ({path_chars(folder)} characters): it "
        f"leaves {max(room, 0)} characters for a name, fewer than [deck] min_name_chars "
        f"({limits.min_name_chars}), within [deck] max_path_chars ({limits.max_path_chars}). "
        "Use a shorter --out or [output] folder."
    )


def check_folder(folder: Path, limits: DeckSettings) -> None:
    """Refuses a folder that leaves no room for a narrated copy of min_name_chars.

    The slide audio PowerPoint embeds is in this folder too, under shorter names.
    """
    room = _room(folder, len(NARRATED_SUFFIX), limits)
    if room < limits.min_name_chars:
        raise _too_long(folder, room, limits)


def check_fits(path: Path, option: str, limits: DeckSettings) -> None:
    """Refuses an output path given on the command line that PowerPoint can't write."""
    length = path_chars(path)
    if length > limits.max_path_chars:
        raise TtsError(
            f"{path} is {length} characters long; PowerPoint can't save a path longer than "
            f"{limits.max_path_chars} ([deck] max_path_chars): choose a shorter {option}."
        )


def _fitted(folder: Path, name: str, suffix: str, after: int, limits: DeckSettings) -> str:
    room = _room(folder, len(suffix) + after, limits)
    if len(name) <= room:
        return name
    if room < limits.min_name_chars:
        raise _too_long(folder, room, limits)
    shortened = _shortened(name, room, limits)
    log.info(
        "The deck's name is long: shortened to stay within PowerPoint's path limit.",
        extra={
            "path": str(folder / f"{shortened}{suffix}"),
            "deck_name": name,
            "max_path_chars": limits.max_path_chars,
        },
    )
    return shortened


def default_folder(deck_path: Path, settings: Settings) -> Path:
    """output/<deck name>/, the name shortened only if it leaves no room for the narrated copy."""
    limits = settings.deck
    root = settings.output_folder
    after = len(os.sep) + limits.min_name_chars + len(NARRATED_SUFFIX)
    return root / _fitted(root, deck_path.stem, "", after, limits)


def output_file(deck_path: Path, folder: Path, suffix: str, limits: DeckSettings) -> Path:
    """folder/<deck name><suffix>, the name shortened to stay within max_path_chars."""
    return folder / f"{_fitted(folder, deck_path.stem, suffix, 0, limits)}{suffix}"
