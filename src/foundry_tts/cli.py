"""The foundry-tts command.

- `foundry-tts --text ...`: text in, one audio file per voice profile out.
- `foundry-tts deck synth deck.pptx`: one audio file per slide from its speaker notes.
- `foundry-tts deck narrate deck.pptx`: the same, then a copy of the deck with the audio embedded.
"""

import argparse
import logging
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import TextIO

import httpx

from foundry_tts import audio_file, deck, deck_narrate, deck_synth, engines, logs, markup, speak
from foundry_tts.config import DEFAULT_CONFIG_FILE, Settings, load_lexicon, load_settings
from foundry_tts.errors import TtsError
from foundry_tts.profiles import SPEECH, Profile

log = logging.getLogger("foundry_tts")

DECK_COMMAND = "deck"


def _add_voice_options(parser: argparse.ArgumentParser, *, several: bool) -> None:
    parser.add_argument(
        "--profile",
        action="append" if several else "store",
        help=(
            "Voice profile from the settings file (default: [defaults] profile). "
            "Repeat it to compare profiles: one audio file each."
            if several
            else "Voice profile from the settings file (default: [defaults] profile)."
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


def _add_run_options(parser: argparse.ArgumentParser) -> None:
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="foundry-tts",
        description=(
            "Turn text into speech with Microsoft Foundry and save the audio file. "
            "Give the text with --text, --file, --ssml, or pipe it in."
        ),
        epilog=(
            "Decks: foundry-tts deck synth deck.pptx makes one audio file per slide from its "
            "speaker notes (foundry-tts deck synth --help)."
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
    _add_voice_options(parser, several=True)
    parser.add_argument(
        "--out",
        type=Path,
        help=(
            "Audio file to write; a folder when several profiles are compared. "
            "Default: timestamped files in output/."
        ),
    )
    _add_run_options(parser)
    return parser


def build_deck_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=f"foundry-tts {DECK_COMMAND}",
        description="Narrate a PowerPoint deck from its speaker notes.",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")
    synth = commands.add_parser(
        "synth",
        help="One audio file per slide with notes, and a manifest.json.",
        description=(
            "Reads the speaker notes of each slide, cleans presenter cues out of them, and "
            "writes slide-01.mp3, ... and manifest.json. The deck is never changed."
        ),
    )
    _add_synth_options(synth)
    narrate = commands.add_parser(
        "narrate",
        help="deck synth, then a copy of the deck with each slide's audio embedded.",
        description=(
            "Makes the audio as deck synth does, then saves <deck>.narrated.pptx next to it with "
            "each slide's audio embedded and playing on its own. Needs desktop PowerPoint on "
            "Windows. The deck is never changed."
        ),
    )
    _add_synth_options(narrate)
    narrate.add_argument(
        "--deck-out",
        type=Path,
        help="Where the narrated deck goes (default: <out folder>/<deck>.narrated.pptx).",
    )
    narrate.add_argument(
        "--skip-synth",
        action="store_true",
        help="Embed the audio and manifest already in the out folder; no Azure call.",
    )
    return parser


def _add_synth_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("deck", type=Path, help="The deck (.pptx).")
    _add_voice_options(parser, several=False)
    parser.add_argument(
        "--out",
        type=Path,
        help="Folder for the audio and the manifest (default: output/<deck name>/).",
    )
    parser.add_argument(
        "--include-hidden", action="store_true", help="Also narrate hidden slides."
    )
    parser.add_argument(
        "--reader",
        choices=deck.READERS,
        default=deck.AUTO,
        help=(
            "How the deck is read: python-pptx (any OS), powerpoint (desktop PowerPoint on "
            "Windows; needed for encrypted or labeled decks), or auto (default: from the file)."
        ),
    )
    _add_run_options(parser)


def _lexicon(settings: Settings, extra: Path | None) -> markup.Lexicon:
    entries = dict(settings.lexicon)
    if extra is not None:
        entries.update(load_lexicon(extra))
    return markup.Lexicon(entries)


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
    if len(profiles) == 1 and args.out is not None:
        return {profiles[0].name: args.out}
    folder = args.out or settings.output_folder
    if len(profiles) > 1 and args.out is not None and args.out.suffix:
        raise TtsError(f"With several profiles, --out is a folder; {args.out} looks like a file.")
    return {
        profile.name: audio_file.default_output_path(
            folder, profile.name, speak.extension(profile, settings), now
        )
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
    lexicon = _lexicon(settings, args.lexicon)

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

    # Every request is built (and checked) before the first call to Azure.
    prepared = {
        profile.name: (
            speak.Requests(profile, [hand_written], speak.extension(profile, settings))
            if hand_written is not None
            else speak.prepare(paragraphs, profile=profile, settings=settings, lexicon=lexicon)
        )
        for profile in profiles
    }

    written = []
    for profile in profiles:
        out = paths[profile.name]
        requests = prepared[profile.name]
        audio = speak.send(requests, settings=settings, client=client, get_token=get_token)
        audio_file.write_audio(audio, out, overwrite=args.overwrite)
        if args.save_ssml and profile.engine == SPEECH:
            # The SSML sent; the parts one after the other when the text was split.
            ssml = "\n".join(requests.bodies)
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
                "requests": len(requests.bodies),
            },
        )
        written.append(out)
    return written


def run_deck(
    args: argparse.Namespace,
    settings: Settings,
    *,
    client: httpx.Client,
    get_token: engines.TokenProvider,
    now: datetime,
) -> Path:
    """foundry-tts deck synth (returns the manifest path) or deck narrate (the narrated deck)."""
    profile = settings.profile(args.profile or settings.default_profile).with_overrides(
        voice=args.voice, language=args.language, instructions=args.instructions
    )
    folder = args.out or settings.output_folder / args.deck.stem

    def synth() -> Path:
        return deck_synth.synth_deck(
            args.deck,
            profile=profile,
            settings=settings,
            lexicon=_lexicon(settings, args.lexicon),
            out=folder,
            reader=args.reader,
            include_hidden=args.include_hidden,
            overwrite=args.overwrite,
            save_ssml=args.save_ssml,
            client=client,
            get_token=get_token,
            now=now,
        )

    if args.command == "synth":
        return synth()
    return deck_narrate.narrate_deck(
        args.deck,
        settings=settings,
        folder=folder,
        deck_out=args.deck_out,
        overwrite=args.overwrite,
        synth=None if args.skip_synth else synth,
    )


def list_profiles(settings: Settings, stdout: TextIO) -> None:
    for name in sorted(settings.profiles):
        marker = "*" if name == settings.default_profile else " "
        stdout.write(f"{marker} {settings.profiles[name].describe()}\n")


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == [DECK_COMMAND]:
        return deck_main(argv[1:])
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


def deck_main(argv: Sequence[str]) -> int:
    args = build_deck_parser().parse_args(argv)
    logs.configure(logging.DEBUG if args.verbose else logging.INFO)
    try:
        settings = load_settings(args.config)
        with httpx.Client(timeout=settings.http.timeout_seconds) as client:
            run_deck(
                args,
                settings,
                client=client,
                get_token=engines.azure_token_provider(),
                now=datetime.now(),
            )
    except TtsError as error:
        log.error(str(error))
        return 1
    return 0
