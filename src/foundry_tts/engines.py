"""The two text to speech engines. Each returns the audio bytes made by Azure.

- `speech`: Azure Speech text to speech REST API, SSML in, audio out.
- `openai`: the `gpt-4o-mini-tts` deployment, Azure OpenAI v1 `/audio/speech` API.

Both sign in with a Microsoft Entra ID token for https://cognitiveservices.azure.com.
"""

import json
import logging
from collections.abc import Callable

import httpx

from foundry_tts.config import Settings
from foundry_tts.errors import TtsError
from foundry_tts.profiles import ENGINES, OPENAI, SPEECH  # noqa: F401 (re-exported)

log = logging.getLogger(__name__)

TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"
# Longest part of an error response body shown to the user.
ERROR_BODY_CHARS = 500

TokenProvider = Callable[[], str]

# File extension of each output format.
_OPENAI_EXTENSIONS = {
    "mp3": ".mp3",
    "wav": ".wav",
    "flac": ".flac",
    "opus": ".opus",
    "aac": ".aac",
}


def azure_token_provider() -> TokenProvider:
    """Entra ID tokens from DefaultAzureCredential (az login on a workstation)."""
    from azure.core.exceptions import ClientAuthenticationError
    from azure.identity import DefaultAzureCredential

    credential = DefaultAzureCredential()

    def get_token() -> str:
        try:
            return credential.get_token(TOKEN_SCOPE).token
        except ClientAuthenticationError as error:
            raise TtsError(
                f"Could not get a Microsoft Entra token. Run az login, then try again. ({error})"
            ) from error

    return get_token


def speech_extension(output_format: str) -> str:
    if "mp3" in output_format:
        return ".mp3"
    if output_format.startswith("riff-"):
        return ".wav"
    raise TtsError(
        f"Output format '{output_format}' is not supported: use an MP3 (audio-*-mp3) "
        "or WAV (riff-*) format."
    )


def openai_extension(response_format: str) -> str:
    try:
        return _OPENAI_EXTENSIONS[response_format]
    except KeyError:
        raise TtsError(
            f"response_format '{response_format}' is not supported: use one of "
            f"{', '.join(_OPENAI_EXTENSIONS)}."
        ) from None


def _check_response(response: httpx.Response, service: str) -> bytes:
    if response.status_code != httpx.codes.OK:
        detail = response.text[:ERROR_BODY_CHARS].strip() or response.reason_phrase
        raise TtsError(
            f"{service} returned HTTP {response.status_code} for {response.request.url}: {detail}"
        )
    if not response.content:
        raise TtsError(f"{service} returned an empty audio file.")
    return response.content


def _post(client: httpx.Client, service: str, url: str, **kwargs) -> httpx.Response:
    try:
        return client.post(url, **kwargs)
    except httpx.HTTPError as error:
        raise TtsError(f"Could not reach {service} at {url}: {error}") from error


def synthesize_speech(
    ssml: str, settings: Settings, client: httpx.Client, get_token: TokenProvider
) -> bytes:
    """Azure Speech: posts the SSML and returns the audio."""
    url = settings.speech_url()
    # Speech takes Entra tokens as aad#<resource ID>#<token>.
    authorization = f"Bearer aad#{settings.speech_resource_id()}#{get_token()}"
    log.info("Calling Azure Speech.", extra={"url": url, "format": settings.speech.output_format})
    response = _post(
        client,
        "Azure Speech",
        url,
        content=ssml.encode("utf-8"),
        headers={
            "Authorization": authorization,
            "Content-Type": "application/ssml+xml; charset=utf-8",
            "X-Microsoft-OutputFormat": settings.speech.output_format,
            "User-Agent": settings.http.user_agent,
        },
    )
    return _check_response(response, "Azure Speech")


def list_speech_voices(
    settings: Settings, client: httpx.Client, get_token: TokenProvider
) -> list[dict]:
    """Azure Speech: the voices the resource offers, as its voice list API returns them."""
    url = settings.speech_voices_url()
    log.info("Listing the Azure Speech voices.", extra={"url": url})
    try:
        response = client.get(
            url,
            headers={
                "Authorization": f"Bearer aad#{settings.speech_resource_id()}#{get_token()}",
                "User-Agent": settings.http.user_agent,
            },
        )
    except httpx.HTTPError as error:
        raise TtsError(f"Could not reach Azure Speech at {url}: {error}") from error
    if response.status_code != httpx.codes.OK:
        detail = response.text[:ERROR_BODY_CHARS].strip() or response.reason_phrase
        raise TtsError(f"Azure Speech returned HTTP {response.status_code} for {url}: {detail}")
    try:
        voices = response.json()
    except ValueError as error:
        raise TtsError(f"Azure Speech returned a voice list that isn't JSON: {error}") from error
    if not isinstance(voices, list):
        raise TtsError("Azure Speech returned a voice list that isn't a JSON array.")
    return voices


def openai_body(text: str, *, voice: str, instructions: str, settings: Settings) -> str:
    """The JSON body of one gpt-4o-mini-tts request (sent as is, so it can be hashed)."""
    limit = settings.openai.max_input_chars
    if len(text) > limit:
        raise TtsError(
            f"The text has {len(text)} characters; the openai engine takes at most {limit}. "
            "Shorten it or use the speech engine."
        )
    body = {
        "model": settings.openai_deployment(),
        "input": text,
        "voice": voice,
        "response_format": settings.openai.response_format,
    }
    if instructions:
        body["instructions"] = instructions
    return json.dumps(body, ensure_ascii=False, sort_keys=True)


def synthesize_openai_body(
    body: str, settings: Settings, client: httpx.Client, get_token: TokenProvider
) -> bytes:
    """gpt-4o-mini-tts: posts a body made by openai_body and returns the audio."""
    url = settings.openai_speech_url()
    log.info(
        "Calling gpt-4o-mini-tts.",
        extra={"url": url, "deployment": settings.openai_deployment()},
    )
    response = _post(
        client,
        "Azure OpenAI",
        url,
        content=body.encode("utf-8"),
        headers={
            "Authorization": f"Bearer {get_token()}",
            "Content-Type": "application/json",
            "User-Agent": settings.http.user_agent,
        },
    )
    return _check_response(response, "Azure OpenAI")


def synthesize_openai(
    text: str,
    *,
    voice: str,
    instructions: str,
    settings: Settings,
    client: httpx.Client,
    get_token: TokenProvider,
) -> bytes:
    """gpt-4o-mini-tts: posts the text and the voice direction, returns the audio."""
    body = openai_body(text, voice=voice, instructions=instructions, settings=settings)
    return synthesize_openai_body(body, settings, client, get_token)
