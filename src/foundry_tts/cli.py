"""The foundry-tts command: text in, audio file out."""

import argparse
import logging
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import TextIO

import httpx

from foundry_tts import audio_file, engines, logs
from foundry_tts.config import DEFAULT_CONFIG_FILE, Settings, load_settings
from foundry_tts.errors import TtsError
from foundry_tts.ssml import build_ssml

log = logging.getLogger("foundry_tts")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="foundry-tts",
        description=(
            "Turn text into speech with Microsoft Foundry and save the audio file. "
            "Give the text with --text, --file, --ssml, or pipe it in."
        ),
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--text", help="The text to say.")
    source.add_argument("--file", type=Path, help="A UTF-8 text file with the text to say.")
    source.add_argument(
        "--ssml", type=Path, help="A hand-written SSML file, sent as is (speech engine only)."
    )
    parser.add_argument(
        "--engine",
        choices=engines.ENGINES,
        default=engines.SPEECH,
        help="speech: Azure Speech voices (default). openai: the gpt-4o-mini-tts deployment.",
    )
    parser.add_argument("--voice", help="Voice name; overrides the settings file.")
    parser.add_argument(
        "--language", help="SSML language, e.g. en-US (speech engine); overrides the settings."
    )
    parser.add_argument(
        "--instructions",
        help="Direction of tone and pace (openai engine); overrides the settings file.",
    )
    parser.add_argument(
        "--out", type=Path, help="Audio file to write. Default: a timestamped file in output/."
    )
    parser.add_argument("--overwrite", action="store_true", help="Replace --out if it exists.")
    parser.add_argument(
        "--save-ssml",
        action="store_true",
        help="Also save the SSML sent to Azure Speech next to the audio (.ssml).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(DEFAULT_CONFIG_FILE),
        help=f"Settings file (default: {DEFAULT_CONFIG_FILE} in the current folder).",
    )
    parser.add_argument("--verbose", action="store_true", help="Log DEBUG messages too.")
    return parser


def run(
    args: argparse.Namespace,
    settings: Settings,
    *,
    client: httpx.Client,
    get_token: engines.TokenProvider,
    stdin: TextIO,
    now: datetime,
) -> Path:
    """Makes the audio and writes it; returns the path of the audio file."""
    ssml: str | None = None
    if args.ssml is not None:
        if args.engine != engines.SPEECH:
            raise TtsError("--ssml works with the speech engine only.")
        ssml = audio_file.read_text(text=None, file=args.ssml, stdin=stdin)
    else:
        text = audio_file.read_text(text=args.text, file=args.file, stdin=stdin)

    if args.engine == engines.SPEECH:
        extension = engines.speech_extension(settings.speech.output_format)
        if ssml is None:
            ssml = build_ssml(
                text,
                voice=args.voice or settings.speech.voice,
                language=args.language or settings.speech.language,
                paragraph_break_ms=settings.speech.paragraph_break_ms,
            )
        audio = engines.synthesize_speech(ssml, settings, client, get_token)
    else:
        extension = engines.openai_extension(settings.openai.response_format)
        audio = engines.synthesize_openai(
            text,
            voice=args.voice or settings.openai.voice,
            instructions=(
                args.instructions
                if args.instructions is not None
                else settings.openai.instructions
            ),
            settings=settings,
            client=client,
            get_token=get_token,
        )

    out = args.out or audio_file.default_output_path(
        settings.output_folder, args.engine, extension, now
    )
    audio_file.write_audio(audio, out, overwrite=args.overwrite)
    if args.save_ssml and ssml is not None:
        audio_file.write_audio(
            ssml.encode("utf-8"), out.with_suffix(".ssml"), overwrite=args.overwrite
        )
    log.info(
        "Audio saved.",
        extra={
            "path": str(out.resolve()),
            "bytes": len(audio),
            "seconds": audio_file.audio_duration_seconds(out),
            "engine": args.engine,
        },
    )
    return out


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logs.configure(logging.DEBUG if args.verbose else logging.INFO)
    try:
        settings = load_settings(args.config)
        with httpx.Client(timeout=settings.http.timeout_seconds) as client:
            run(
                args,
                settings,
                client=client,
                get_token=engines.azure_token_provider(),
                stdin=sys.stdin,
                now=datetime.now(),
            )
    except TtsError as error:
        log.error(str(error))
        return 1
    return 0
