"""foundry-tts deck narrate: a copy of the deck with each slide's audio embedded.

The audio comes from `deck synth` (run first, or reused with `--skip-synth`); desktop PowerPoint
embeds it (see powerpoint.py and docs/decisions/0001 and 0002). The source deck is never changed.
With --auto-advance each slide moves on when its narration ends; --video also exports an MP4.

A rerun into the same folder replaces the narrated copy and video it wrote before (listed in the
manifest) and, through deck synth, only synthesizes the slides that changed.
"""

import logging
from collections.abc import Callable
from pathlib import Path

from foundry_tts import deck, deck_synth, powerpoint
from foundry_tts.config import Settings
from foundry_tts.errors import TtsError

log = logging.getLogger(__name__)

NARRATED_SUFFIX = ".narrated.pptx"
VIDEO_SUFFIX = ".narrated.mp4"
PPTX = ".pptx"
MP4 = ".mp4"


def narrated_path(deck_path: Path, folder: Path, deck_out: Path | None) -> Path:
    return deck_out or folder / f"{deck_path.stem}{NARRATED_SUFFIX}"


def video_path(deck_path: Path, folder: Path) -> Path:
    return folder / f"{deck_path.stem}{VIDEO_SUFFIX}"


def narrations_from(manifest: dict, folder: Path, deck_path: Path) -> list[powerpoint.Narration]:
    """The audio of each slide, from a manifest written for this deck."""
    if manifest["deck"] != deck_path.name:
        raise TtsError(
            f"The manifest in {folder} is for {manifest['deck']}, not {deck_path.name}."
        )
    narrations = []
    for entry in manifest["slides"]:
        audio = folder / entry["file"]
        if not audio.is_file():
            raise TtsError(
                f"Slide {entry['slide']}: {audio} is missing. Run without --skip-synth."
            )
        narrations.append(powerpoint.Narration(slide=entry["slide"], audio=audio))
    return narrations


def _earlier_outputs(manifest_path: Path) -> set[str]:
    """The narrated copy and video an earlier run wrote (resolved paths), from its manifest."""
    if not manifest_path.exists():
        return set()
    try:
        manifest = deck_synth.load_manifest(manifest_path)
    except TtsError:
        return set()  # deck synth reports a bad manifest; here it only means nothing is ours
    return set(manifest.get(deck_synth.NARRATED_OUTPUTS, []))


def _check_output(path: Path, suffix: str, deck_path: Path, overwrite: bool, ours: set[str]):
    if path.suffix.lower() != suffix:
        raise TtsError(f"{path} must end with {suffix}.")
    if path.resolve() == deck_path.resolve():
        raise TtsError(
            "The narrated copy can't replace the source deck: choose another --deck-out."
        )
    if path.exists() and not overwrite and str(path.resolve()) not in ours:
        raise TtsError(f"{path} already exists. Use --overwrite to replace it.")


def _show_seconds(manifest: dict, timings: dict[int, float]) -> float | None:
    """How long the self-running show lasts: the timings of the slides that aren't hidden."""
    if not timings:
        return None
    hidden = {s["slide"] for s in manifest["skipped"] if s["reason"] == deck_synth.HIDDEN}
    hidden |= {s["slide"] for s in manifest["slides"] if s["hidden"]}
    return round(sum(t for number, t in timings.items() if number not in hidden), 2)


def narrate_deck(
    deck_path: Path,
    *,
    settings: Settings,
    folder: Path,
    deck_out: Path | None,
    overwrite: bool,
    synth: Callable[[], Path] | None,
    auto_advance: bool = False,
    video_out: Path | None = None,
) -> Path:
    """Embeds the audio of the manifest in folder and saves the narrated copy; returns its path.

    `synth` makes the audio and returns the manifest path, or is None to reuse the manifest
    already in the folder (--skip-synth). `video_out` also exports the copy to MP4, and turns
    auto_advance on.
    """
    out = narrated_path(deck_path, folder, deck_out)
    manifest_path = folder / deck_synth.MANIFEST
    ours = _earlier_outputs(manifest_path)
    _check_output(out, PPTX, deck_path, overwrite, ours)
    if video_out is not None:
        _check_output(video_out, MP4, deck_path, overwrite, ours)
        if not auto_advance:
            log.info("A video needs slide timings: --auto-advance is turned on.")
            auto_advance = True
    source_encrypted = deck.file_kind(deck_path) == deck.OLE
    if video_out is not None and source_encrypted:
        log.warning(
            "The deck is encrypted (a sensitivity label or a password); the MP4 video won't be: "
            "anyone with the file can watch it. Share it as you would the deck's content.",
            extra={"path": str(video_out)},
        )

    manifest_path = synth() if synth is not None else manifest_path
    manifest = deck_synth.load_manifest(manifest_path)
    narrations = narrations_from(manifest, folder, deck_path)
    if not narrations:
        raise TtsError("The manifest has no slide audio to embed.")

    for path in (out, video_out):
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.unlink(missing_ok=True)  # PowerPoint won't replace a file on its own
    advance = (
        powerpoint.Advance(
            gap_seconds=settings.deck.advance_gap_seconds,
            silent_slide_seconds=settings.deck.silent_slide_seconds,
        )
        if auto_advance
        else None
    )
    video = (
        powerpoint.Video(
            path=video_out,
            default_slide_seconds=settings.deck.silent_slide_seconds,
            vertical_resolution=settings.video.vertical_resolution,
            frames_per_second=settings.video.frames_per_second,
            quality=settings.video.quality,
            timeout_seconds=settings.video.timeout_seconds,
            poll_seconds=settings.video.poll_seconds,
        )
        if video_out is not None
        else None
    )
    result = powerpoint.narrate(
        deck_path,
        narrations,
        out,
        shape_name=settings.deck.audio_shape_name,
        margin_points=settings.deck.off_slide_margin_points,
        advance=advance,
        video=video,
    )
    for item in result.placed:
        log.info(
            "Narration embedded.",
            extra={
                "slide": item.slide,
                "seconds": item.seconds,
                "replaced": item.replaced,
                "advance_seconds": result.timings.get(item.slide),
            },
        )
    encrypted = {"source": source_encrypted, "narrated": deck.file_kind(out) == deck.OLE}
    if encrypted["source"] and not encrypted["narrated"]:
        log.warning(
            "The source deck is encrypted (a sensitivity label or a password) but the narrated "
            "copy isn't: check its label in PowerPoint before sharing it.",
            extra={"path": str(out.resolve())},
        )
    written = [out] + ([video_out] if video_out is not None else [])
    manifest[deck_synth.NARRATED_OUTPUTS] = sorted(
        ours | {str(path.resolve()) for path in written}
    )
    deck_synth.write_manifest(manifest, manifest_path)
    log.info(
        "Narrated deck saved.",
        extra={
            "path": str(out.resolve()),
            "slides": len(result.placed),
            "seconds": round(sum(item.seconds for item in result.placed), 2),
            "show_seconds": _show_seconds(manifest, result.timings),
            "encrypted": encrypted,
        },
    )
    if video_out is not None:
        log.info(
            "Video exported.",
            extra={"path": str(video_out.resolve()), "bytes": video_out.stat().st_size},
        )
    return out
