"""foundry-tts deck synth: one audio file per slide from its speaker notes, and a manifest.

Everything is read and checked before the first Azure call: the deck, the notes of every slide,
the request bodies and the output files. Then each slide is synthesized in turn; the manifest is
written last, so a manifest always describes a complete run.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx

from foundry_tts import audio_file, deck, engines, markup, notes, speak
from foundry_tts.config import Settings
from foundry_tts.errors import TtsError
from foundry_tts.markup import Lexicon
from foundry_tts.profiles import Profile

log = logging.getLogger(__name__)

MANIFEST = "manifest.json"
MANIFEST_VERSION = 1
SLIDE_PREFIX = "slide-"
MIN_NUMBER_WIDTH = 2
NO_NOTES = "no notes"
HIDDEN = "hidden"


@dataclass(frozen=True)
class SlideJob:
    slide: deck.Slide
    requests: speak.Requests
    cleanups: dict[str, int]
    audio_path: Path


def _jobs(
    slides: list[deck.Slide],
    *,
    profile: Profile,
    settings: Settings,
    lexicon: Lexicon,
    folder: Path,
    include_hidden: bool,
) -> tuple[list[SlideJob], list[dict]]:
    width = max(MIN_NUMBER_WIDTH, len(str(len(slides))))
    jobs, skipped = [], []
    for slide in slides:
        if slide.hidden and not include_hidden:
            skipped.append({"slide": slide.number, "reason": HIDDEN})
            continue
        cleaned = notes.clean(slide.notes, cue_pause_ms=settings.deck.cue_pause_ms)
        paragraphs = markup.parse(cleaned.text, allow_empty=True)
        if not paragraphs:
            skipped.append({"slide": slide.number, "reason": NO_NOTES})
            continue
        if cleaned.counts:
            log.info("Notes cleaned.", extra={"slide": slide.number, "cleanups": cleaned.counts})
        try:
            requests = speak.prepare(
                paragraphs, profile=profile, settings=settings, lexicon=lexicon
            )
        except TtsError as error:
            raise TtsError(f"Slide {slide.number}: {error}") from error
        name = f"{SLIDE_PREFIX}{slide.number:0{width}d}{requests.extension}"
        jobs.append(SlideJob(slide, requests, cleaned.counts, folder / name))
    return jobs, skipped


def _ssml_paths(job: SlideJob) -> list[Path]:
    """Where --save-ssml writes each request: slide-01.ssml, or slide-01.1.ssml, ... if split."""
    if len(job.requests.bodies) == 1:
        return [job.audio_path.with_suffix(".ssml")]
    return [
        job.audio_path.with_suffix(f".{part}.ssml")
        for part in range(1, len(job.requests.bodies) + 1)
    ]


def synth_deck(
    deck_path: Path,
    *,
    profile: Profile,
    settings: Settings,
    lexicon: Lexicon,
    out: Path | None,
    reader: str,
    include_hidden: bool,
    overwrite: bool,
    save_ssml: bool,
    client: httpx.Client,
    get_token: engines.TokenProvider,
    now: datetime,
) -> Path:
    """Writes the audio of each slide with notes and the manifest; returns the manifest path."""
    slides, used_reader = deck.read_slides(deck_path, reader)
    folder = out or settings.output_folder / deck_path.stem
    jobs, skipped = _jobs(
        slides,
        profile=profile,
        settings=settings,
        lexicon=lexicon,
        folder=folder,
        include_hidden=include_hidden,
    )
    if not jobs:
        raise TtsError(
            f"No slide of {deck_path} has speaker notes to say "
            f"({len(slides)} slides, {len(skipped)} skipped)."
        )
    manifest_path = folder / MANIFEST
    planned = [manifest_path] + [job.audio_path for job in jobs]
    if save_ssml and profile.engine == engines.SPEECH:
        planned += [path for job in jobs for path in _ssml_paths(job)]
    for path in planned:
        if path.exists() and not overwrite:
            raise TtsError(f"{path} already exists. Use --overwrite to replace it.")
    log.info(
        "Deck read.",
        extra={
            "deck": str(deck_path),
            "reader": used_reader,
            "slides": len(slides),
            "to_say": len(jobs),
            "skipped": skipped,
            "profile": profile.name,
        },
    )

    entries = []
    for job in jobs:
        try:
            audio = speak.send(job.requests, settings=settings, client=client, get_token=get_token)
        except TtsError as error:
            raise TtsError(
                f"Slide {job.slide.number}: {error} The slides before it were saved; "
                "no manifest was written."
            ) from error
        audio_file.write_audio(audio, job.audio_path, overwrite=overwrite)
        if save_ssml and profile.engine == engines.SPEECH:
            for body, path in zip(job.requests.bodies, _ssml_paths(job), strict=True):
                audio_file.write_audio(body.encode("utf-8"), path, overwrite=overwrite)
        seconds = audio_file.audio_duration_seconds(job.audio_path)
        log.info(
            "Slide audio saved.",
            extra={
                "slide": job.slide.number,
                "path": str(job.audio_path.resolve()),
                "bytes": len(audio),
                "seconds": seconds,
                "requests": len(job.requests.bodies),
            },
        )
        entries.append(
            {
                "slide": job.slide.number,
                "file": job.audio_path.name,
                "seconds": seconds,
                "bytes": len(audio),
                "requests": len(job.requests.bodies),
                "hash": job.requests.hash,
                "hidden": job.slide.hidden,
                "cleanups": job.cleanups,
            }
        )

    known = [entry["seconds"] for entry in entries if entry["seconds"] is not None]
    manifest = {
        "version": MANIFEST_VERSION,
        "deck": deck_path.name,
        "reader": used_reader,
        "created": now.isoformat(timespec="seconds"),
        "profile": profile.name,
        "engine": profile.engine,
        "voice": profile.voice,
        "slide_count": len(slides),
        "total_seconds": round(sum(known), 2),
        "slides": entries,
        "skipped": skipped,
    }
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    audio_file.write_audio(text.encode("utf-8"), manifest_path, overwrite=overwrite)
    log.info(
        "Manifest saved.",
        extra={
            "path": str(manifest_path.resolve()),
            "slides": len(entries),
            "total_seconds": manifest["total_seconds"],
        },
    )
    return manifest_path
