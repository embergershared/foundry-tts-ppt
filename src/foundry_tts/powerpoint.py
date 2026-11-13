"""Desktop PowerPoint on Windows, through COM automation (pywin32).

- `read_slides`: the slides of a deck python-pptx can't open (a sensitivity label, a password, an
  old .ppt).
- `narrate`: a narrated copy of a deck, each slide's audio embedded and set to play on its own;
  optionally each slide advancing when its narration ends, and an MP4 export.

As in the PowerShell prototype, the source deck is opened read-only and without a window, it is
never saved (a copy is saved under a new name), and PowerPoint is quit only if this run started
it. PowerPoint opens a labeled deck with the signed-in user's rights.
"""

import logging
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from foundry_tts.deck import Slide
from foundry_tts.errors import TtsError

log = logging.getLogger(__name__)

APPLICATION = "PowerPoint.Application"
MSO_TRUE = -1
MSO_FALSE = 0
# PpPlaceholderType.ppPlaceholderBody: the notes text on a notes page.
PP_PLACEHOLDER_BODY = 2
# PpSaveAsFileType.ppSaveAsOpenXMLPresentation: .pptx, whatever the source format.
PP_SAVE_AS_PPTX = 24
MS_PER_SECOND = 1000
# MsoAnimEffect.msoAnimEffectMediaPlay and MsoAnimTriggerType.msoAnimTriggerAfterPrevious.
MSO_ANIM_EFFECT_MEDIA_PLAY = 83
MSO_ANIM_TRIGGER_AFTER_PREVIOUS = 3
# PpSlideShowAdvanceMode.ppSlideShowUseSlideTimings: the show follows each slide's timing.
PP_SLIDE_SHOW_USE_SLIDE_TIMINGS = 2
# PpMediaTaskStatus of Presentation.CreateVideoStatus.
PP_MEDIA_TASK_DONE = 3
PP_MEDIA_TASK_FAILED = 4
# Every shape this tool inserts carries this tag, so a rerun finds and replaces it even if the
# shape was renamed; the shape name (a setting) is found too.
TAG_NAME = "FOUNDRY_TTS"
TAG_NARRATION = "narration"


@dataclass(frozen=True)
class Narration:
    """The audio to embed in one slide."""

    slide: int
    audio: Path


@dataclass(frozen=True)
class Placed:
    """What PowerPoint did for one slide."""

    slide: int
    seconds: float  # the audio length PowerPoint reports
    replaced: int  # narration shapes of an earlier run removed


@dataclass(frozen=True)
class Advance:
    """Slides advance on their own: a narrated slide when its audio ends plus a gap."""

    gap_seconds: float
    silent_slide_seconds: float  # a slide without narration


@dataclass(frozen=True)
class Video:
    """An MP4 export of the narrated deck (Presentation.CreateVideo)."""

    path: Path
    default_slide_seconds: float
    vertical_resolution: int
    frames_per_second: int
    quality: int
    timeout_seconds: float
    poll_seconds: float


def _com_message(error: Exception) -> str:
    """The most useful text of a pywintypes.com_error."""
    details = getattr(error, "excepinfo", None)
    if details and len(details) > 2 and details[2]:
        return str(details[2]).strip()
    return str(error)


@contextmanager
def _powerpoint(path: Path) -> Iterator[tuple[object, type[Exception]]]:
    """PowerPoint.Application and the COM error type; quits PowerPoint after if it started it."""
    if sys.platform != "win32":
        raise TtsError(
            f"{path} has to go through desktop PowerPoint, which needs Windows. "
            "For reading, save an unencrypted copy as .pptx."
        )
    try:
        import pythoncom
        import pywintypes
        import win32com.client
    except ImportError as error:
        raise TtsError(
            f"pywin32 is missing, so PowerPoint can't be used ({error}). "
            "Install the locked requirements again."
        ) from error

    pythoncom.CoInitialize()
    try:
        try:
            win32com.client.GetActiveObject(APPLICATION)
            was_running = True
        except pywintypes.com_error:
            was_running = False
        try:
            app = win32com.client.Dispatch(APPLICATION)
        except pywintypes.com_error as error:
            raise TtsError(f"Desktop PowerPoint isn't available: {_com_message(error)}") from error
        try:
            yield app, pywintypes.com_error
        finally:
            if not was_running:
                app.Quit()
            del app
    finally:
        pythoncom.CoUninitialize()


@contextmanager
def _open_read_only(app, path: Path, com_error: type[Exception]) -> Iterator[object]:
    log.info("Opening the deck in PowerPoint, read-only.", extra={"deck": str(path)})
    try:
        presentation = app.Presentations.Open(
            str(path.resolve()), MSO_TRUE, MSO_FALSE, MSO_FALSE
        )  # ReadOnly, Untitled, WithWindow
    except com_error as error:
        raise TtsError(f"PowerPoint could not open {path}: {_com_message(error)}") from error
    try:
        yield presentation
    finally:
        presentation.Close()
        del presentation


def _notes(slide) -> str:
    placeholders = slide.NotesPage.Shapes.Placeholders
    for index in range(1, placeholders.Count + 1):
        shape = placeholders.Item(index)
        if shape.PlaceholderFormat.Type == PP_PLACEHOLDER_BODY and shape.HasTextFrame == MSO_TRUE:
            # PowerPoint separates paragraphs with CR; python-pptx with LF.
            return str(shape.TextFrame.TextRange.Text).replace("\r", "\n")
    return ""


def read_slides(path: Path) -> list[Slide]:
    with _powerpoint(path) as (app, com_error), _open_read_only(app, path, com_error) as deck:
        try:
            slides = []
            for number in range(1, deck.Slides.Count + 1):
                slide = deck.Slides.Item(number)
                hidden = slide.SlideShowTransition.Hidden == MSO_TRUE
                slides.append(Slide(number=number, hidden=hidden, notes=_notes(slide)))
            return slides
        except com_error as error:
            raise TtsError(f"PowerPoint could not read {path}: {_com_message(error)}") from error


def _is_narration(shape, shape_name: str) -> bool:
    return shape.Name == shape_name or shape.Tags.Item(TAG_NAME) == TAG_NARRATION


def remove_narration(slide, shape_name: str) -> int:
    """Deletes the narration shapes an earlier run inserted; returns how many."""
    removed = 0
    for index in range(slide.Shapes.Count, 0, -1):  # backwards: deleting renumbers the rest
        shape = slide.Shapes.Item(index)
        if _is_narration(shape, shape_name):
            shape.Delete()
            removed += 1
    return removed


def _start_automatically(slide, shape, number: int) -> None:
    """Makes the shape's play effect the slide's first, starting as the slide shows.

    PlayOnEntry adds a "media play" effect at the end of the slide's animations, started by a
    click (measured in PowerPoint, 2026-11-12). It is moved first and set to start after the
    previous event (the slide appearing) with no delay, so the narration starts on its own,
    before any of the slide's own click animations.
    """
    sequence = slide.TimeLine.MainSequence
    for index in range(1, sequence.Count + 1):
        effect = sequence.Item(index)
        if effect.EffectType == MSO_ANIM_EFFECT_MEDIA_PLAY and effect.Shape.Id == shape.Id:
            effect.MoveTo(1)
            effect.Timing.TriggerType = MSO_ANIM_TRIGGER_AFTER_PREVIOUS
            effect.Timing.TriggerDelayTime = 0
            return
    raise TtsError(f"Slide {number}: PowerPoint added no play effect for the narration.")


def place_narrations(
    presentation, narrations: list[Narration], *, shape_name: str, margin_points: float
) -> list[Placed]:
    """Embeds each slide's audio just right of the slide, playing on entry, hidden in the show.

    Narration from an earlier run is removed from every slide first, so a slide whose notes were
    removed loses its old audio too. Other media are left alone.
    """
    count = presentation.Slides.Count
    beyond = sorted(n.slide for n in narrations if not 1 <= n.slide <= count)
    if beyond:
        raise TtsError(f"The deck has {count} slides; there is audio for slide(s) {beyond}.")
    by_slide = {n.slide: n for n in narrations}
    left = presentation.PageSetup.SlideWidth + margin_points
    placed = []
    for number in range(1, count + 1):
        slide = presentation.Slides.Item(number)
        replaced = remove_narration(slide, shape_name)
        narration = by_slide.get(number)
        if narration is None:
            continue
        shape = slide.Shapes.AddMediaObject2(
            str(narration.audio.resolve()), MSO_FALSE, MSO_TRUE, left, 0
        )  # LinkToFile, SaveWithDocument, Left, Top
        shape.Name = shape_name
        shape.Tags.Add(TAG_NAME, TAG_NARRATION)
        play = shape.AnimationSettings.PlaySettings
        play.PlayOnEntry = MSO_TRUE
        play.HideWhileNotPlaying = MSO_TRUE
        _start_automatically(slide, shape, number)
        length_ms = shape.MediaFormat.Length
        if length_ms <= 0:
            raise TtsError(f"PowerPoint reports no length for {narration.audio} (slide {number}).")
        placed.append(Placed(number, round(length_ms / MS_PER_SECOND, 2), replaced))
    return placed


def set_timings(presentation, placed: list[Placed], advance: Advance) -> dict[int, float]:
    """Every slide advances on its own (a click still works); returns its time, in seconds.

    A narrated slide lasts its audio plus the gap; a slide without narration lasts
    silent_slide_seconds. The show is set to use these timings.
    """
    narrated = {item.slide: item.seconds for item in placed}
    timings = {}
    for number in range(1, presentation.Slides.Count + 1):
        transition = presentation.Slides.Item(number).SlideShowTransition
        seconds = (
            round(narrated[number] + advance.gap_seconds, 2)
            if number in narrated
            else advance.silent_slide_seconds
        )
        transition.AdvanceOnTime = MSO_TRUE
        transition.AdvanceTime = seconds
        timings[number] = seconds
    presentation.SlideShowSettings.AdvanceMode = PP_SLIDE_SHOW_USE_SLIDE_TIMINGS
    return timings


def export_video(
    presentation,
    video: Video,
    *,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Exports the deck to MP4 with its timings and narration; waits until PowerPoint is done."""
    log.info("Exporting the video; this takes a while.", extra={"path": str(video.path)})
    presentation.CreateVideo(
        str(video.path.resolve()),
        True,  # UseTimingsAndNarrations
        video.default_slide_seconds,
        video.vertical_resolution,
        video.frames_per_second,
        video.quality,
    )
    deadline = clock() + video.timeout_seconds
    while True:
        status = presentation.CreateVideoStatus
        if status == PP_MEDIA_TASK_DONE:
            return
        if status == PP_MEDIA_TASK_FAILED:
            raise TtsError(f"PowerPoint could not export the video {video.path}.")
        if clock() > deadline:
            raise TtsError(
                f"The video export did not finish within {video.timeout_seconds:g} s "
                "([video] timeout_seconds)."
            )
        sleep(video.poll_seconds)


@dataclass(frozen=True)
class Narrated:
    placed: list[Placed]
    timings: dict[int, float]  # empty without Advance


def narrate(
    path: Path,
    narrations: list[Narration],
    out_path: Path,
    *,
    shape_name: str,
    margin_points: float,
    advance: Advance | None = None,
    video: Video | None = None,
) -> Narrated:
    """Saves a copy of the deck at out_path (.pptx) with the narration embedded.

    With `advance`, the slides advance on their own; with `video`, the copy is also exported to
    MP4 (which needs `advance`, or narrated slides would be cut at default_slide_seconds).
    """
    if video is not None and advance is None:
        raise TtsError("A video export needs the slides to advance on their own.")
    with _powerpoint(path) as (app, com_error), _open_read_only(app, path, com_error) as deck:
        try:
            placed = place_narrations(
                deck, narrations, shape_name=shape_name, margin_points=margin_points
            )
            timings = set_timings(deck, placed, advance) if advance is not None else {}
            deck.SaveAs(str(out_path.resolve()), PP_SAVE_AS_PPTX)
            if video is not None:
                export_video(deck, video)
        except com_error as error:
            raise TtsError(
                f"PowerPoint could not narrate {path}: {_com_message(error)}"
            ) from error
        return Narrated(placed, timings)
