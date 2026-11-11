"""The two text to speech engines. Each returns the audio bytes made by Azure.

- `speech`: Azure Speech text to speech REST API, SSML in, audio out.
- `openai`: the `gpt-4o-mini-tts` deployment, Azure OpenAI v1 `/audio/speech` API.

Both sign in with a Microsoft Entra ID token for https://cognitiveservices.azure.com.
"""

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
    limit = settings.openai.max_input_chars
    if len(text) > limit:
        raise TtsError(
            f"The text has {len(text)} characters; the openai engine takes at most {limit}. "
            "Shorten it or use the speech engine."
        )
    url = settings.openai_speech_url()
    body = {
        "model": settings.openai_deployment(),
        "input": text,
        "voice": voice,
        "response_format": settings.openai.response_format,
    }
    if instructions:
        body["instructions"] = instructions
    log.info("Calling gpt-4o-mini-tts.", extra={"url": url, "deployment": body["model"]})
    response = _post(
        client,
        "Azure OpenAI",
        url,
        json=body,
        headers={"Authorization": f"Bearer {get_token()}", "User-Agent": settings.http.user_agent},
    )
    return _check_response(response, "Azure OpenAI")
