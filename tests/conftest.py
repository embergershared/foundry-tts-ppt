"""Shared test setup: src/ on the import path, settings and a stubbed Azure."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import httpx  # noqa: E402
import pytest  # noqa: E402

from foundry_tts.config import load_settings  # noqa: E402

CONFIG = ROOT / "foundry-tts.toml"
RESOURCE_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/providers/"
    "Microsoft.CognitiveServices/accounts/fdy-test"
)
ENV = {
    "FOUNDRY_RESOURCE_ID": RESOURCE_ID,
    "FOUNDRY_REGION": "eastus2",
    "FOUNDRY_OPENAI_ENDPOINT": "https://fdy-test.openai.azure.com/",
    "FOUNDRY_TTS_DEPLOYMENT": "gpt-4o-mini-tts",
}
FAKE_AUDIO = b"ID3fake-mp3-bytes"


@pytest.fixture
def settings():
    return load_settings(CONFIG, env=ENV)


class RecordingTransport(httpx.MockTransport):
    """Answers every request with one response and keeps the requests."""

    def __init__(self, status: int = 200, content: bytes = FAKE_AUDIO):
        self.requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(status, content=content)

        super().__init__(handler)


@pytest.fixture
def transport():
    return RecordingTransport()


@pytest.fixture
def client(transport):
    with httpx.Client(transport=transport) as http_client:
        yield http_client


def fake_token() -> str:
    return "entra-token"
