"""The foundry-tts command: text in, one audio file per voice profile out."""

import argparse
import logging
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import TextIO

import httpx

from foundry_tts import audio_file, engines, logs, markup
from foundry_tts.config import DEFAULT_CONFIG_FILE, Settings, load_lexicon, load_settings
from foundry_tts.errors import TtsError
from foundry_tts.profiles import SPEECH, Profile
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
        "--ssml", type=Path, help="A hand-written SSML file, sent as is (speech profiles only)."
    )
    source.add_argument(
        "--list-profiles", action="store_true", help="List the voice profiles and stop."
    )
    parser.add_argument(
        "--profile",
        action="append",
        help=(
            "Voice profile from the settings file (default: [defaults] profile). "
            "Repeat it to compare profiles: one audio file each."
        ),
    )
    parser.add_argument("--voice", help="Voice name; overrides the profile's voice.")
    parser.add_argument("--language", help="SSML language, e.g. fr-FR (speech profiles).")
    parser.add_argument(
        "--instructions", help="Direction of tone and pace (openai profiles); overrides it."
    )
    parser.add_argument(
        "--lexicon",
        type=Path,
        help="A TOML file with a [lexicon] table, added to the settings file's lexicon.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help=(
            "Audio file to write; a folder when several profiles are compared. "
            "Default: timestamped files in output/."
        ),
    )
    parser.add_argument("--overwrite", action="store_true", help="Replace existing files.")
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


def choose_profiles(args: argparse.Namespace, settings: Settings) -> list[Profile]:
    """The profiles to run, in the order given, with the command-line overrides applied."""
    names = args.profile or [settings.default_profile]
    if len(set(names)) != len(names):
        raise TtsError("A profile is given more than once.")
    overrides = {
        "voice": args.voice,
        "language": args.language,
        "instructions": args.instructions,
    }
    if len(names) > 1 and any(value is not None for value in overrides.values()):
        raise TtsError("--voice, --language and --instructions apply to one profile only.")
    profiles = [settings.profile(name).with_overrides(**overrides) for name in names]
    if args.ssml is not None:
        if len(profiles) > 1:
            raise TtsError("--ssml sends one hand-written SSML file: give one profile only.")
        if profiles[0].engine != SPEECH:
            raise TtsError(f"--ssml needs a speech profile; '{profiles[0].name}' is openai.")
    return profiles


def output_paths(
    args: argparse.Namespace, settings: Settings, profiles: list[Profile], now: datetime
) -> dict[str, Path]:
    """Where each profile's audio goes."""

    def extension(profile: Profile) -> str:
        if profile.engine == SPEECH:
            return engines.speech_extension(settings.speech.output_format)
        return engines.openai_extension(settings.openai.response_format)

    if len(profiles) == 1 and args.out is not None:
        return {profiles[0].name: args.out}
    folder = args.out or settings.output_folder
    if len(profiles) > 1 and args.out is not None and args.out.suffix:
        raise TtsError(f"With several profiles, --out is a folder; {args.out} looks like a file.")
    return {
        profile.name: audio_file.default_output_path(folder, profile.name, extension(profile), now)
        for profile in profiles
    }


def run(
    args: argparse.Namespace,
    settings: Settings,
    *,
    client: httpx.Client,
    get_token: engines.TokenProvider,
    stdin: TextIO,
    now: datetime,
) -> list[Path]:
    """Makes the audio for each profile and writes it; returns the paths written."""
    profiles = choose_profiles(args, settings)
    lexicon_entries = dict(settings.lexicon)
    if args.lexicon is not None:
        lexicon_entries.update(load_lexicon(args.lexicon))
    lexicon = markup.Lexicon(lexicon_entries)

    hand_written: str | None = None
    paragraphs: list[markup.Paragraph] = []
    if args.ssml is not None:
        hand_written = audio_file.read_text(text=None, file=args.ssml, stdin=stdin)
    else:
        paragraphs = markup.parse(
            audio_file.read_text(text=args.text, file=args.file, stdin=stdin)
        )

    paths = output_paths(args, settings, profiles, now)
    for out in paths.values():
        if out.exists() and not args.overwrite:
            raise TtsError(f"{out} already exists. Use --overwrite to replace it.")

    written = []
    for profile in profiles:
        out = paths[profile.name]
        ssml: str | None = None
        if profile.engine == SPEECH:
            ssml = hand_written or build_ssml(
                paragraphs,
                profile=profile,
                language=settings.speech.language,
                paragraph_break_ms=settings.speech.paragraph_break_ms,
                lexicon=lexicon,
            )
            audio = engines.synthesize_speech(ssml, settings, client, get_token)
        else:
            audio = engines.synthesize_openai(
                markup.to_plain_text(paragraphs, lexicon),
                voice=profile.voice,
                instructions=profile.instructions or "",
                settings=settings,
                client=client,
                get_token=get_token,
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
                "profile": profile.name,
                "engine": profile.engine,
                "voice": profile.voice,
            },
        )
        written.append(out)
    return written


def list_profiles(settings: Settings, stdout: TextIO) -> None:
    for name in sorted(settings.profiles):
        marker = "*" if name == settings.default_profile else " "
        stdout.write(f"{marker} {settings.profiles[name].describe()}\n")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logs.configure(logging.DEBUG if args.verbose else logging.INFO)
    try:
        settings = load_settings(args.config)
        if args.list_profiles:
            list_profiles(settings, sys.stdout)
            return 0
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
