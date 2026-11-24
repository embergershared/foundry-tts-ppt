"""The foundry-tts command.

- `foundry-tts --text ...`: text in, one audio file per voice profile out.
- `foundry-tts deck synth deck.pptx`: one audio file per slide from its speaker notes.
- `foundry-tts deck narrate deck.pptx`: the same, then a copy of the deck with the audio embedded.
- `foundry-tts deck sample deck.pptx`: one slide spoken, to try a voice on the deck.
- `foundry-tts profile list|check|save`: the voice profiles as JSON, for scripts/Start-Demo.ps1.
- `foundry-tts voice list`: the Azure Speech voices the resource offers, filtered.
"""

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import TextIO

import httpx

from foundry_tts import (
    audio_file,
    deck,
    deck_narrate,
    deck_synth,
    engines,
    logs,
    markup,
    output_names,
    speak,
    voices,
)
from foundry_tts.config import (
    DEFAULT_CONFIG_FILE,
    Settings,
    load_lexicon,
    load_settings,
    save_profile,
)
from foundry_tts.errors import TtsError
from foundry_tts.profiles import SPEECH, Profile

log = logging.getLogger("foundry_tts")

DECK_COMMAND = "deck"
PROFILE_COMMAND = "profile"
VOICE_COMMAND = "voice"
GENDERS = ("female", "male", "neutral")
# Profile settings the command line can override, as --<name>.
OVERRIDES = ("voice", "language", "style", "rate", "pitch", "temperature", "instructions")


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
        "--style", help="Speaking style (<mstts:express-as>), e.g. narrator (speech profiles)."
    )
    # A value starting with "-" needs the = form (--rate=-5%), or argparse reads it as an option.
    parser.add_argument(
        "--rate",
        help="Speaking rate, e.g. --rate=-5%%, +10%% or slow (speech profiles).",
    )
    parser.add_argument("--pitch", help="Pitch, e.g. +2st, --pitch=-5%% or low (speech profiles).")
    parser.add_argument(
        "--temperature",
        type=float,
        help="0 to 1, lower is steadier (speech profiles with an HD voice).",
    )
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
    _add_config_options(parser)


def _add_config_options(parser: argparse.ArgumentParser) -> None:
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
            "speaker notes (foundry-tts deck synth --help). Voices: foundry-tts voice list "
            "--language en-US lists the voices the resource offers."
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
    narrate.add_argument(
        "--auto-advance",
        action="store_true",
        help=(
            "Each slide moves on when its narration ends ([deck] advance_gap_seconds later); a "
            "slide without narration shows [deck] silent_slide_seconds. The deck runs on its own."
        ),
    )
    narrate.add_argument(
        "--video",
        action="store_true",
        help="Also export the narrated deck to MP4 (<deck>.narrated.mp4); implies --auto-advance.",
    )
    narrate.add_argument("--video-out", type=Path, help="Where the MP4 goes; implies --video.")
    sample = commands.add_parser(
        "sample",
        help="Speak one slide's notes with the chosen voice, to try it before the whole deck.",
        description=(
            "Speaks the notes of the first slide deck synth would narrate (or --slide), cleaned "
            "as deck synth cleans them, and saves <out folder>/sample.mp3, replaced each time."
        ),
    )
    _add_deck_input(sample)
    sample.add_argument(
        "--slide", type=int, help="The slide to speak, even if hidden (default: the first)."
    )
    _add_config_options(sample)
    return parser


def build_profile_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=f"foundry-tts {PROFILE_COMMAND}",
        description="The voice profiles of the settings file, as JSON on stdout (for scripts).",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")
    listing = commands.add_parser(
        "list", help="Every profile, the default, and the settings each profile's voice accepts."
    )
    _add_config_options(listing)
    check = commands.add_parser(
        "check", help="The profile with the command-line overrides applied, or the reason not."
    )
    _add_voice_options(check, several=False)
    _add_config_options(check)
    save = commands.add_parser(
        "save",
        help="Save the profile with the overrides applied as a new profile in the settings file.",
    )
    save.add_argument("name", help="The new profile's name: letters, digits, '-' and '_'.")
    _add_voice_options(save, several=False)
    _add_config_options(save)
    return parser


def _family(value: str) -> str:
    """--family: a voice family name, case ignored."""
    for family in voices.FAMILIES:
        if value.casefold() == family.casefold():
            return family
    raise argparse.ArgumentTypeError(
        f"'{value}' isn't a voice family; use one of: {', '.join(voices.FAMILIES)}."
    )


def build_voice_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=f"foundry-tts {VOICE_COMMAND}",
        description="The Azure Speech voices the resource offers.",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")
    listing = commands.add_parser(
        "list",
        help="The voices, one per line, or as JSON with --json.",
        description=(
            "Asks the resource's voice list API for its voices and prints those that pass the "
            "filters: name (what a profile's voice or --voice takes), gender, family, status and "
            "styles (what --style takes)."
        ),
    )
    listing.add_argument(
        "--language", help="A locale (en-US) or a language (en: every en-* locale)."
    )
    listing.add_argument(
        "--gender", type=str.lower, choices=GENDERS, help="female, male or neutral."
    )
    listing.add_argument(
        "--family",
        type=_family,
        help=f"The voice family: {', '.join(repr(family) for family in voices.FAMILIES)}.",
    )
    listing.add_argument(
        "--search",
        help="Text in the voice's name, styles, personalities or scenarios: Grant, narrator.",
    )
    listing.add_argument(
        "--json",
        action="store_true",
        help='Print {"voices": [...]} with every detail (for scripts).',
    )
    _add_config_options(listing)
    return parser


def _add_deck_input(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("deck", type=Path, help="The deck (.pptx).")
    _add_voice_options(parser, several=False)
    parser.add_argument(
        "--out",
        type=Path,
        help="Folder for the audio and the manifest (default: output/<deck name>/).",
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


def _add_synth_options(parser: argparse.ArgumentParser) -> None:
    _add_deck_input(parser)
    parser.add_argument(
        "--include-hidden", action="store_true", help="Also narrate hidden slides."
    )
    _add_run_options(parser)


def _lexicon(settings: Settings, extra: Path | None) -> markup.Lexicon:
    entries = dict(settings.lexicon)
    if extra is not None:
        entries.update(load_lexicon(extra))
    return markup.Lexicon(entries)


def _overrides(args: argparse.Namespace) -> dict:
    """The profile settings given on the command line (None: keep the profile's)."""
    return {key: getattr(args, key) for key in OVERRIDES}


def chosen_profile(args: argparse.Namespace, settings: Settings) -> Profile:
    """The one profile of a deck or profile command, with the command-line overrides applied."""
    return settings.profile(args.profile or settings.default_profile).with_overrides(
        **_overrides(args)
    )


def choose_profiles(args: argparse.Namespace, settings: Settings) -> list[Profile]:
    """The profiles to run, in the order given, with the command-line overrides applied."""
    names = args.profile or [settings.default_profile]
    if len(set(names)) != len(names):
        raise TtsError("A profile is given more than once.")
    overrides = _overrides(args)
    if len(names) > 1 and any(value is not None for value in overrides.values()):
        options = ", ".join(f"--{key}" for key in OVERRIDES)
        raise TtsError(f"{options} apply to one profile only.")
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
            speak.hand_written(hand_written, profile, settings)
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
    """deck synth (returns the manifest path), deck narrate (the narrated deck) or deck sample
    (the sample's audio)."""
    profile = chosen_profile(args, settings)
    folder = args.out or output_names.default_folder(args.deck, settings)

    if args.command == "sample":
        return deck_synth.sample_slide(
            args.deck,
            profile=profile,
            settings=settings,
            lexicon=_lexicon(settings, args.lexicon),
            out=folder,
            reader=args.reader,
            slide_number=args.slide,
            client=client,
            get_token=get_token,
        )

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
        auto_advance=args.auto_advance,
        video_out=(
            args.video_out or deck_narrate.video_path(args.deck, folder, settings.deck)
            if args.video or args.video_out
            else None
        ),
    )


def list_profiles(settings: Settings, stdout: TextIO) -> None:
    for name in sorted(settings.profiles):
        marker = "*" if name == settings.default_profile else " "
        stdout.write(f"{marker} {settings.profiles[name].describe()}\n")


def run_profile(args: argparse.Namespace, settings: Settings) -> dict:
    """profile list, check or save; the JSON to print."""
    if args.command == "list":
        return {
            "default": settings.default_profile,
            "profiles": [settings.profiles[name].to_dict() for name in sorted(settings.profiles)],
        }
    profile = chosen_profile(args, settings)
    if args.command == "save":
        profile = replace(profile, name=args.name)
        save_profile(args.config, profile)
        log.info(
            "Profile saved.",
            extra={"profile": profile.name, "path": str(args.config.resolve())},
        )
    return profile.to_dict()


def run_voice(
    args: argparse.Namespace,
    settings: Settings,
    *,
    client: httpx.Client,
    get_token: engines.TokenProvider,
) -> list[voices.Voice]:
    """voice list: the voices that pass the filters."""
    offered = voices.parse(engines.list_speech_voices(settings, client, get_token))
    selected = voices.select(
        offered,
        language=args.language,
        gender=args.gender,
        family=args.family,
        search=args.search,
    )
    log.info("Voices listed.", extra={"offered": len(offered), "selected": len(selected)})
    return selected


def write_voices(selected: list[voices.Voice], stdout: TextIO, *, as_json: bool) -> None:
    """voice list's output: one line per voice, or {"voices": [...]} for scripts."""
    if as_json:
        payload = {"voices": [voice.to_dict() for voice in selected]}
        stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    else:
        stdout.writelines(f"{voice.describe()}\n" for voice in selected)


def voice_main(argv: Sequence[str], stdout: TextIO) -> int:
    args = build_voice_parser().parse_args(argv)
    logs.configure(logging.DEBUG if args.verbose else logging.INFO)
    try:
        settings = load_settings(args.config)
        with httpx.Client(timeout=settings.http.timeout_seconds) as client:
            selected = run_voice(
                args, settings, client=client, get_token=engines.azure_token_provider()
            )
    except TtsError as error:
        log.error(str(error))
        return 1
    write_voices(selected, stdout, as_json=args.json)
    return 0


def profile_main(argv: Sequence[str], stdout: TextIO) -> int:
    args = build_profile_parser().parse_args(argv)
    logs.configure(logging.DEBUG if args.verbose else logging.INFO)
    try:
        # No Azure call: the environment variables are not needed, so .env isn't read.
        result = run_profile(args, load_settings(args.config, env={}))
    except TtsError as error:
        log.error(str(error))
        return 1
    stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == [DECK_COMMAND]:
        return deck_main(argv[1:])
    if argv[:1] == [PROFILE_COMMAND]:
        return profile_main(argv[1:], sys.stdout)
    if argv[:1] == [VOICE_COMMAND]:
        return voice_main(argv[1:], sys.stdout)
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
            result = run_deck(
                args,
                settings,
                client=client,
                get_token=engines.azure_token_provider(),
                now=datetime.now(),
            )
    except TtsError as error:
        log.error(str(error))
        return 1
    # The result's path, alone on stdout, for scripts (scripts/Start-Demo.ps1); logs go to stderr.
    sys.stdout.write(f"{result.resolve()}\n")
    return 0
