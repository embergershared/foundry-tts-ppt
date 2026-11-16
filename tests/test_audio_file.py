import io
import wave
from datetime import datetime
from pathlib import Path

import pytest

from foundry_tts import audio_file
from foundry_tts.errors import TtsError


class FakeStdin(io.StringIO):
    def __init__(self, text: str = "", tty: bool = False):
        super().__init__(text)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def test_text_option_wins():
    assert audio_file.read_text(text="Hi", file=None, stdin=FakeStdin("piped")) == "Hi"


def test_file_is_read_as_utf8_without_bom(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_bytes("﻿Bonjour à tous".encode())
    assert audio_file.read_text(text=None, file=path, stdin=FakeStdin()) == "Bonjour à tous"


def test_piped_text_is_read():
    assert audio_file.read_text(text=None, file=None, stdin=FakeStdin("from a pipe")) == (
        "from a pipe"
    )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"text": None, "file": None, "stdin": FakeStdin(tty=True)}, "No text given"),
        ({"text": "   ", "file": None, "stdin": FakeStdin()}, "empty"),
        ({"text": None, "file": Path("missing.txt"), "stdin": FakeStdin()}, "not found"),
    ],
)
def test_bad_input_is_refused(kwargs, message):
    with pytest.raises(TtsError, match=message):
        audio_file.read_text(**kwargs)


def test_non_utf8_file_is_refused(tmp_path):
    path = tmp_path / "latin1.txt"
    path.write_bytes("caf\xe9".encode("latin-1"))
    with pytest.raises(TtsError, match="not UTF-8"):
        audio_file.read_text(text=None, file=path, stdin=FakeStdin())


def test_default_output_path_is_timestamped():
    path = audio_file.default_output_path(
        Path("output"), "speech", ".mp3", datetime(2026, 11, 10, 9, 5, 7)
    )
    assert path == Path("output") / "20261110-090507-speech.mp3"


def test_write_creates_folders_and_refuses_to_overwrite(tmp_path):
    path = tmp_path / "a" / "b.mp3"
    audio_file.write_audio(b"one", path, overwrite=False)
    with pytest.raises(TtsError, match="already exists"):
        audio_file.write_audio(b"two", path, overwrite=False)
    audio_file.write_audio(b"two", path, overwrite=True)
    assert path.read_bytes() == b"two"
    assert sorted(p.name for p in path.parent.iterdir()) == ["b.mp3"]  # no temporary file left


def test_duration_of_a_wav_file(tmp_path):
    path = tmp_path / "tone.wav"
    rate = 8000
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x00\x00" * rate * 2)  # 2 seconds
    assert audio_file.audio_duration_seconds(path) == 2.0


def test_duration_of_unknown_bytes_is_none(tmp_path):
    path = tmp_path / "x.mp3"
    path.write_bytes(b"not audio")
    assert audio_file.audio_duration_seconds(path) is None
