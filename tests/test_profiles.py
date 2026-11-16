import pytest

from foundry_tts.errors import TtsError
from foundry_tts.profiles import (
    DRAGON_HD,
    DRAGON_HD_OMNI,
    MAI_VOICE,
    STANDARD,
    Profile,
    honors_break,
    validate,
    voice_family,
)


@pytest.mark.parametrize(
    ("voice", "family"),
    [
        ("en-US-Ava:DragonHDLatestNeural", DRAGON_HD),
        ("en-us-ava:DragonHDOmniLatestNeural", DRAGON_HD_OMNI),
        ("en-US-Tiana:DragonHDFlashLatestNeural", DRAGON_HD),
        ("en-US-Harper:MAI-Voice-2.1", MAI_VOICE),
        ("en-US-Harper:MAI-Voice-2.1-Flash", MAI_VOICE),
        ("en-US-AvaMultilingualNeural", STANDARD),
    ],
)
def test_voice_family(voice, family):
    assert voice_family(voice) == family


def speech(**kwargs) -> Profile:
    return Profile(
        name="p",
        engine="speech",
        voice=kwargs.pop("voice", "en-US-X:DragonHDLatestNeural"),
        **kwargs,
    )


def test_mai_voices_are_the_only_family_without_breaks():
    assert not honors_break(speech(voice="en-US-Harper:MAI-Voice-2.1"))
    assert honors_break(speech())
    assert honors_break(speech(voice="en-US-AvaMultilingualNeural"))
    assert not honors_break(Profile(name="o", engine="openai", voice="marin"))


@pytest.mark.parametrize(
    ("profile", "message"),
    [
        (Profile(name="p", engine="azure", voice="v"), "engine must be one of"),
        (Profile(name="p", engine="speech", voice=" "), "voice is empty"),
        (Profile(name="p", engine="openai", voice="marin", style="calm"), "style doesn't apply"),
        (Profile(name="p", engine="openai", voice="marin", rate="-5%"), "rate doesn't apply"),
        (speech(instructions="Calm."), "instructions doesn't apply"),
        (speech(rate="slower"), "rate 'slower'"),
        (speech(pitch="+2"), "pitch '\\+2'"),
        (speech(temperature=1.5), "between 0.0 and 1.0"),
        (speech(voice="en-US-Harper:MAI-Voice-2.1", temperature=0.5), "HD voices only"),
        (speech(voice="en-US-AvaMultilingualNeural", temperature=0.5), "HD voices only"),
    ],
)
def test_unsupported_settings_are_refused(profile, message):
    with pytest.raises(TtsError, match=message):
        validate(profile)


@pytest.mark.parametrize(
    "profile",
    [
        speech(rate="-5%", pitch="+2st", temperature=0.6, style="calm", language="en-GB"),
        speech(voice="en-US-Harper:MAI-Voice-2.1", style="narrator", rate="slow", pitch="low"),
        speech(voice="en-us-ava:DragonHDOmniLatestNeural", temperature=0.3, pitch="-10Hz"),
        Profile(name="o", engine="openai", voice="marin", instructions="Calm."),
    ],
)
def test_supported_settings_pass(profile):
    validate(profile)


def test_overrides_are_applied_and_checked_again():
    profile = speech(temperature=0.6)
    assert profile.with_overrides(voice=None, language=None, instructions=None) is profile
    changed = profile.with_overrides(
        voice="en-US-Andrew:DragonHDLatestNeural", language="en-GB", instructions=None
    )
    assert (changed.voice, changed.language, changed.temperature) == (
        "en-US-Andrew:DragonHDLatestNeural",
        "en-GB",
        0.6,
    )
    with pytest.raises(TtsError, match="HD voices only"):
        profile.with_overrides(
            voice="en-US-Harper:MAI-Voice-2.1", language=None, instructions=None
        )
    with pytest.raises(TtsError, match="instructions doesn't apply"):
        profile.with_overrides(voice=None, language=None, instructions="Calm.")


def test_describe_lists_only_what_is_set():
    assert (
        speech(temperature=0.6).describe()
        == "p  speech  en-US-X:DragonHDLatestNeural  temperature=0.6"
    )
