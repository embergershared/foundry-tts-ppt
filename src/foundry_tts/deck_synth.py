"""foundry-tts deck synth: one audio file per slide from its speaker notes, and a manifest.

Everything is read and checked before the first Azure call: the deck, the notes of every slide,
the request bodies and the output files. Then each slide is synthesized in turn; the manifest is
written last, so a manifest always describes a complete run. A rerun reuses the audio of the
slides whose requests are unchanged (same hash).
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
# Manifest key: the files deck narrate wrote (narrated copy, video), which a rerun may replace.
NARRATED_OUTPUTS = "narrated_outputs"
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


def load_manifest(path: Path) -> dict:
    """A manifest this tool wrote (same version)."""
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise TtsError(f"No manifest at {path}: run without --skip-synth first.") from None
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise TtsError(f"{path} is not a valid manifest: {error}") from error
    if not isinstance(manifest, dict) or manifest.get("version") != MANIFEST_VERSION:
        version = manifest.get("version") if isinstance(manifest, dict) else None
        raise TtsError(
            f"{path} has manifest version {version!r}; this tool writes version "
            f"{MANIFEST_VERSION}. Use --overwrite to make the audio again."
        )
    return manifest


def _previous(manifest_path: Path, deck_path: Path, overwrite: bool) -> dict | None:
    """The manifest of an earlier run for this deck, whose files a rerun may replace or reuse.

    None with --overwrite (everything is made again) or when there is none.
    """
    if overwrite or not manifest_path.exists():
        return None
    manifest = load_manifest(manifest_path)
    if manifest.get("deck") != deck_path.name:
        raise TtsError(
            f"{manifest_path} is for {manifest.get('deck')}, not {deck_path.name}: choose "
            "another --out, or use --overwrite."
        )
    return manifest


def _owned_names(previous: dict | None) -> set[str]:
    """Files an earlier run wrote: a rerun replaces them without --overwrite."""
    if previous is None:
        return set()
    names = {MANIFEST}
    for entry in previous["slides"]:
        stem = Path(entry["file"]).stem
        names.add(entry["file"])
        names.add(f"{stem}.ssml")
        names.update(f"{stem}.{part}.ssml" for part in range(1, entry["requests"] + 1))
    return names


def _reusable(job: SlideJob, previous: dict | None) -> dict | None:
    """The earlier manifest entry for this slide, if exactly the same requests made its audio."""
    if previous is None:
        return None
    for entry in previous["slides"]:
        if (
            entry["slide"] == job.slide.number
            and entry["hash"] == job.requests.hash
            and entry["file"] == job.audio_path.name
            and job.audio_path.is_file()
        ):
            return entry
    return None


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
    """Writes the audio of each slide with notes and the manifest; returns the manifest path.

    A rerun into the same folder only synthesizes the slides whose requests changed (their hash
    differs from the earlier manifest's); the others keep their audio. --overwrite makes all of
    it again.
    """
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
    previous = _previous(manifest_path, deck_path, overwrite)
    owned = _owned_names(previous)
    writes_ssml = save_ssml and profile.engine == engines.SPEECH
    planned = [manifest_path] + [job.audio_path for job in jobs]
    if writes_ssml:
        planned += [path for job in jobs for path in _ssml_paths(job)]
    for path in planned:
        if path.exists() and not overwrite and path.name not in owned:
            raise TtsError(f"{path} already exists. Use --overwrite to replace it.")
    reuse = {job.slide.number: _reusable(job, previous) for job in jobs}
    log.info(
        "Deck read.",
        extra={
            "deck": str(deck_path),
            "reader": used_reader,
            "slides": len(slides),
            "to_say": len(jobs),
            "to_synthesize": sum(entry is None for entry in reuse.values()),
            "skipped": skipped,
            "profile": profile.name,
        },
    )

    entries = []
    for job in jobs:
        kept = reuse[job.slide.number]
        if kept is not None:
            log.info(
                "Slide audio reused: its requests are unchanged.",
                extra={"slide": job.slide.number, "path": str(job.audio_path.resolve())},
            )
            entries.append({**kept, "hidden": job.slide.hidden, "cleanups": job.cleanups})
            continue
        try:
            audio = speak.send(job.requests, settings=settings, client=client, get_token=get_token)
        except TtsError as error:
            raise TtsError(
                f"Slide {job.slide.number}: {error} The slides before it were saved; "
                "no manifest was written."
            ) from error
        audio_file.write_audio(audio, job.audio_path, overwrite=True)
        if writes_ssml:
            for body, path in zip(job.requests.bodies, _ssml_paths(job), strict=True):
                audio_file.write_audio(body.encode("utf-8"), path, overwrite=True)
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
    _remove_stale(previous, entries, folder)

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
    if previous is not None and previous.get(NARRATED_OUTPUTS):
        manifest[NARRATED_OUTPUTS] = previous[NARRATED_OUTPUTS]
    write_manifest(manifest, manifest_path)
    log.info(
        "Manifest saved.",
        extra={
            "path": str(manifest_path.resolve()),
            "slides": len(entries),
            "synthesized": sum(entry is None for entry in reuse.values()),
            "total_seconds": manifest["total_seconds"],
        },
    )
    return manifest_path


def _remove_stale(previous: dict | None, entries: list[dict], folder: Path) -> None:
    """Deletes the audio of slides an earlier run said that have nothing to say any more."""
    if previous is None:
        return
    current = {entry["file"] for entry in entries}
    for entry in previous["slides"]:
        if entry["file"] not in current:
            stale = folder / entry["file"]
            stale.unlink(missing_ok=True)
            log.info(
                "Old slide audio removed.", extra={"slide": entry["slide"], "path": str(stale)}
            )


def write_manifest(manifest: dict, path: Path) -> None:
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    audio_file.write_audio(text.encode("utf-8"), path, overwrite=True)
