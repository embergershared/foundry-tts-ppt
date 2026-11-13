"""foundry-tts deck narrate: a copy of the deck with each slide's audio embedded.

The audio comes from `deck synth` (run first, or reused with `--skip-synth`); desktop PowerPoint
embeds it (see powerpoint.py and docs/decisions/0001 and 0002). The source deck is never changed.
"""

import json
import logging
from pathlib import Path

from foundry_tts import deck, deck_synth, powerpoint
from foundry_tts.config import Settings
from foundry_tts.errors import TtsError

log = logging.getLogger(__name__)

NARRATED_SUFFIX = ".narrated.pptx"


def narrated_path(deck_path: Path, folder: Path, deck_out: Path | None) -> Path:
    return deck_out or folder / f"{deck_path.stem}{NARRATED_SUFFIX}"


def load_manifest(path: Path) -> dict:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise TtsError(f"No manifest at {path}: run without --skip-synth first.") from None
    except json.JSONDecodeError as error:
        raise TtsError(f"{path} is not a valid manifest: {error}") from error
    if manifest.get("version") != deck_synth.MANIFEST_VERSION:
        raise TtsError(
            f"{path} has manifest version {manifest.get('version')!r}; this tool writes "
            f"version {deck_synth.MANIFEST_VERSION}. Run without --skip-synth."
        )
    return manifest


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


def narrate_deck(
    deck_path: Path,
    *,
    settings: Settings,
    folder: Path,
    deck_out: Path | None,
    overwrite: bool,
    synth,
) -> Path:
    """Embeds the audio of the manifest in folder and saves the narrated copy; returns its path.

    `synth` makes the audio and returns the manifest path, or is None to reuse the manifest
    already in the folder (--skip-synth).
    """
    out = narrated_path(deck_path, folder, deck_out)
    if out.suffix.lower() != ".pptx":
        raise TtsError(f"The narrated deck is saved as .pptx; {out} has another extension.")
    if out.resolve() == deck_path.resolve():
        raise TtsError(
            "The narrated copy can't replace the source deck: choose another --deck-out."
        )
    if out.exists() and not overwrite:
        raise TtsError(f"{out} already exists. Use --overwrite to replace it.")
    source_kind = deck.file_kind(deck_path)

    manifest_path = synth() if synth is not None else folder / deck_synth.MANIFEST
    manifest = load_manifest(manifest_path)
    narrations = narrations_from(manifest, folder, deck_path)
    if not narrations:
        raise TtsError("The manifest has no slide audio to embed.")

    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()  # --overwrite: PowerPoint's SaveAs won't replace a file on its own
    placed = powerpoint.narrate(
        deck_path,
        narrations,
        out,
        shape_name=settings.deck.audio_shape_name,
        margin_points=settings.deck.off_slide_margin_points,
    )
    for item in placed:
        log.info(
            "Narration embedded.",
            extra={"slide": item.slide, "seconds": item.seconds, "replaced": item.replaced},
        )
    encrypted = {"source": source_kind == deck.OLE, "narrated": deck.file_kind(out) == deck.OLE}
    if encrypted["source"] and not encrypted["narrated"]:
        log.warning(
            "The source deck is encrypted (a sensitivity label or a password) but the narrated "
            "copy isn't: check its label in PowerPoint before sharing it.",
            extra={"path": str(out.resolve())},
        )
    log.info(
        "Narrated deck saved.",
        extra={
            "path": str(out.resolve()),
            "slides": len(placed),
            "seconds": round(sum(item.seconds for item in placed), 2),
            "encrypted": encrypted,
        },
    )
    return out
