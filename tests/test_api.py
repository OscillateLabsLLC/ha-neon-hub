"""Tests for the HANA API client, especially token lifecycle management."""

import base64
import json

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.neon_hub.api import (
    NeonHubAuthError,
    NeonHubClient,
    NeonHubConnectionError,
    _jwt_expiration,
)

from .conftest import (
    TEST_BASE_URL,
    TEST_PASSWORD,
    TEST_USERNAME,
    auth_payload,
    make_jwt,
)

LOGIN_URL = f"{TEST_BASE_URL}/auth/login"
REFRESH_URL = f"{TEST_BASE_URL}/auth/refresh"
TTS_URL = f"{TEST_BASE_URL}/neon/get_tts"

WAV_BYTES = b"RIFF....WAVEfake-audio"
TTS_PAYLOAD = {"encoded_audio": base64.b64encode(WAV_BYTES).decode()}


def make_client(hass: HomeAssistant) -> NeonHubClient:
    session = async_get_clientsession(hass)
    return NeonHubClient(session, TEST_BASE_URL, TEST_USERNAME, TEST_PASSWORD)


def count_calls(aioclient_mock: AiohttpClientMocker, url_fragment: str) -> int:
    return sum(1 for call in aioclient_mock.mock_calls if url_fragment in str(call[1]))


def last_request_json(aioclient_mock: AiohttpClientMocker) -> dict:
    sent = aioclient_mock.mock_calls[-1][2]
    if isinstance(sent, (bytes, str)):
        return json.loads(sent)
    return sent


async def test_token_reused_across_requests(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A valid access token is reused; login happens exactly once."""
    aioclient_mock.post(LOGIN_URL, json=auth_payload())
    aioclient_mock.post(TTS_URL, json=TTS_PAYLOAD)
    client = make_client(hass)

    assert await client.async_get_tts("hi", "en-us", "female") == WAV_BYTES
    assert await client.async_get_tts("again", "en-us", "female") == WAV_BYTES

    assert count_calls(aioclient_mock, "/auth/login") == 1
    headers = aioclient_mock.mock_calls[-1][3]
    assert headers["Authorization"].startswith("Bearer ")


async def test_expiring_access_token_triggers_refresh(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An access token inside the refresh horizon is refreshed proactively.

    Regression guard for the Node-app bug: checking only the refresh token's
    expiry leaves an expired access token in use.
    """
    aioclient_mock.post(LOGIN_URL, json=auth_payload(access_expires_in=30))
    aioclient_mock.post(REFRESH_URL, json=auth_payload())
    aioclient_mock.post(TTS_URL, json=TTS_PAYLOAD)
    client = make_client(hass)
    await client.async_login()

    assert await client.async_get_tts("hi", "en-us", "female") == WAV_BYTES

    assert count_calls(aioclient_mock, "/auth/refresh") == 1
    assert count_calls(aioclient_mock, "/auth/login") == 1


async def test_rejected_refresh_falls_back_to_login(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A rejected refresh token falls back to a full login."""
    aioclient_mock.post(LOGIN_URL, json=auth_payload(access_expires_in=30))
    aioclient_mock.post(REFRESH_URL, status=401)
    aioclient_mock.post(TTS_URL, json=TTS_PAYLOAD)
    client = make_client(hass)
    await client.async_login()

    assert await client.async_get_tts("hi", "en-us", "female") == WAV_BYTES
    assert count_calls(aioclient_mock, "/auth/login") == 2


async def test_fully_expired_tokens_relogin(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Expired access AND refresh tokens go straight to login."""
    aioclient_mock.post(
        LOGIN_URL, json=auth_payload(access_expires_in=-10, refresh_expires_in=-10)
    )
    aioclient_mock.post(TTS_URL, json=TTS_PAYLOAD)
    client = make_client(hass)
    await client.async_login()

    assert await client.async_get_tts("hi", "en-us", "female") == WAV_BYTES
    assert count_calls(aioclient_mock, "/auth/refresh") == 0
    assert count_calls(aioclient_mock, "/auth/login") == 2


async def test_persistent_401_raises_auth_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 401 on an endpoint forces one re-login, then surfaces as auth error."""
    aioclient_mock.post(LOGIN_URL, json=auth_payload())
    aioclient_mock.post(TTS_URL, status=401)
    client = make_client(hass)

    with pytest.raises(NeonHubAuthError):
        await client.async_get_tts("hi", "en-us", "female")
    assert count_calls(aioclient_mock, "/auth/login") == 2


async def test_login_rejected_raises_auth_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 4xx from login (e.g. unknown user 404) raises NeonHubAuthError."""
    aioclient_mock.post(LOGIN_URL, status=404)
    client = make_client(hass)

    with pytest.raises(NeonHubAuthError):
        await client.async_login()


async def test_malformed_login_response(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A login response missing tokens raises a connection error."""
    aioclient_mock.post(LOGIN_URL, json={"username": TEST_USERNAME})
    client = make_client(hass)

    with pytest.raises(NeonHubConnectionError):
        await client.async_login()


async def test_server_error_raises_connection_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 500 from an endpoint surfaces as a connection error."""
    aioclient_mock.post(LOGIN_URL, json=auth_payload())
    aioclient_mock.post(TTS_URL, status=500)
    client = make_client(hass)

    with pytest.raises(NeonHubConnectionError):
        await client.async_get_tts("hi", "en-us", "female")


async def test_malformed_tts_response(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A TTS response without audio raises a connection error."""
    aioclient_mock.post(LOGIN_URL, json=auth_payload())
    aioclient_mock.post(TTS_URL, json={"nope": True})
    client = make_client(hass)

    with pytest.raises(NeonHubConnectionError):
        await client.async_get_tts("hi", "en-us", "female")


async def test_get_stt(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """STT decodes transcripts and sends base64 audio."""
    aioclient_mock.post(LOGIN_URL, json=auth_payload())
    aioclient_mock.post(
        f"{TEST_BASE_URL}/neon/get_stt",
        json={"transcripts": ["hello world"], "parser_data": {}},
    )
    client = make_client(hass)

    assert await client.async_get_stt(b"audio", "en-us") == ["hello world"]
    sent = last_request_json(aioclient_mock)
    assert base64.b64decode(sent["encoded_audio"]) == b"audio"


async def test_get_stt_malformed(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An STT response without transcripts raises a connection error."""
    aioclient_mock.post(LOGIN_URL, json=auth_payload())
    aioclient_mock.post(f"{TEST_BASE_URL}/neon/get_stt", json={"parser_data": {}})
    client = make_client(hass)

    with pytest.raises(NeonHubConnectionError):
        await client.async_get_stt(b"audio", "en-us")


async def test_get_response_and_malformed(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Skill responses return the answer; missing answers raise."""
    aioclient_mock.post(LOGIN_URL, json=auth_payload())
    aioclient_mock.post(
        f"{TEST_BASE_URL}/neon/get_response",
        json={"answer": "It is sunny.", "lang_code": "en-us"},
    )
    client = make_client(hass)
    assert await client.async_get_response("weather?", "en-us") == "It is sunny."

    aioclient_mock.clear_requests()
    aioclient_mock.post(LOGIN_URL, json=auth_payload())
    aioclient_mock.post(f"{TEST_BASE_URL}/neon/get_response", json={})
    with pytest.raises(NeonHubConnectionError):
        await client.async_get_response("weather?", "en-us")


async def test_llm_ask_and_malformed(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """LLM queries pass history through and return the response text."""
    aioclient_mock.post(LOGIN_URL, json=auth_payload())
    aioclient_mock.post(
        f"{TEST_BASE_URL}/llm/chatgpt",
        json={"response": "42", "history": [["user", "q"], ["llm", "42"]]},
    )
    client = make_client(hass)

    assert await client.async_llm_ask("chatgpt", "q", [["user", "prior"]]) == "42"
    sent = last_request_json(aioclient_mock)
    assert sent["history"] == [["user", "prior"]]

    aioclient_mock.clear_requests()
    aioclient_mock.post(LOGIN_URL, json=auth_payload())
    aioclient_mock.post(f"{TEST_BASE_URL}/llm/chatgpt", json={})
    with pytest.raises(NeonHubConnectionError):
        await client.async_llm_ask("chatgpt", "q", [])


async def test_check_ready(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """/status is plain text; only 'Ready' counts as ready."""
    aioclient_mock.get(f"{TEST_BASE_URL}/status", text="Ready")
    client = make_client(hass)
    assert await client.async_check_ready() is True

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{TEST_BASE_URL}/status", text="Starting")
    assert await client.async_check_ready() is False


async def test_check_ready_connection_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A transport failure on /status raises a connection error."""
    aioclient_mock.get(f"{TEST_BASE_URL}/status", exc=TimeoutError())
    client = make_client(hass)

    with pytest.raises(NeonHubConnectionError):
        await client.async_check_ready()


async def test_login_without_tokens_raises_auth_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A login response with null tokens surfaces as an auth error."""
    aioclient_mock.post(
        LOGIN_URL,
        json={"access_token": None, "refresh_token": None, "client_id": "x"},
    )
    client = make_client(hass)

    with pytest.raises(NeonHubAuthError):
        await client.async_get_tts("hi", "en-us", "female")


async def test_identity_malformed(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An identity response missing fields raises a connection error."""
    aioclient_mock.get(f"{TEST_BASE_URL}/hub/identity", json={"hub_id": "x"})
    client = make_client(hass)

    with pytest.raises(NeonHubConnectionError):
        await client.async_get_identity()


async def test_hub_config_tolerates_malformed_shapes(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Unexpected /hub/config shapes degrade to None fields, not errors."""
    client = make_client(hass)

    aioclient_mock.get(f"{TEST_BASE_URL}/hub/config", json=[])
    config = await client.async_get_hub_config()
    assert config.tts_module is None
    assert config.stt_module is None
    assert config.llm_persona is None

    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"{TEST_BASE_URL}/hub/config",
        json={"tts": "not-a-dict", "llm": {"id": "Fallback"}},
    )
    config = await client.async_get_hub_config()
    assert config.tts_module is None
    assert config.llm_persona == "Fallback"

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{TEST_BASE_URL}/hub/config", exc=TimeoutError())
    with pytest.raises(NeonHubConnectionError):
        await client.async_get_hub_config()


def test_jwt_expiration_malformed() -> None:
    """Garbage tokens decode to an expiration of 0 (refresh eagerly)."""
    assert _jwt_expiration("not-a-jwt") == 0
    assert _jwt_expiration("") == 0
    assert _jwt_expiration("a.b.c") == 0
    assert _jwt_expiration(make_jwt(3600)) > 0
