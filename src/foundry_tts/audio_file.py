"""Reads the text to say and writes the audio file."""

import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import TextIO

import mutagen

from foundry_tts.errors import TtsError

log = logging.getLogger(__name__)


def read_text(*, text: str | None, file: Path | None, stdin: TextIO) -> str:
    """The text from --text, else from --file (UTF-8, BOM removed), else from standard input."""
    if text is not None:
        source = text
    elif file is not None:
        try:
            source = file.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            raise TtsError(f"Text file not found: {file}") from None
        except UnicodeDecodeError as error:
            raise TtsError(f"{file} is not UTF-8 text: {error}") from error
    elif not stdin.isatty():
        source = stdin.read()
    else:
        raise TtsError("No text given: use --text, --file or --ssml, or pipe the text in.")
    if not source.strip():
        raise TtsError("The text is empty; there is nothing to say.")
    return source


def default_output_path(folder: Path, engine: str, extension: str, now: datetime) -> Path:
    return folder / f"{now:%Y%m%d-%H%M%S}-{engine}{extension}"


def write_audio(audio: bytes, path: Path, *, overwrite: bool) -> None:
    """Writes the audio through a temporary file, so a failure never leaves a partial file."""
    if path.exists() and not overwrite:
        raise TtsError(f"{path} already exists. Use --overwrite to replace it.")
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}-", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(audio)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def audio_duration_seconds(path: Path) -> float | None:
    """Length of the audio, or None when the format isn't recognized."""
    try:
        info = mutagen.File(path)
    except mutagen.MutagenError as error:
        log.warning(
            "Could not read the audio length.", extra={"path": str(path), "error": str(error)}
        )
        return None
    if info is None or info.info is None:
        return None
    return round(info.info.length, 2)
