"""Fixtures for Neon Hub tests."""

import base64
import json
import time

import pytest
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.neon_hub.const import CONF_BASE_URL, DOMAIN

TEST_HOST = "hana.test.local"
TEST_BASE_URL = f"https://{TEST_HOST}"
TEST_HUB_ID = "fierce-amber-node"
TEST_USERNAME = "homeassistant"
TEST_PASSWORD = "hunter2"

IDENTITY_PAYLOAD = {
    "hub_id": TEST_HUB_ID,
    "display_name": "Neon Hub",
    "version": "0.1.1a23",
    "warning": None,
}

HUB_CONFIG_PAYLOAD = {
    "tts": {"module": "ovos-tts-plugin-kokoro"},
    "stt": {"module": "ovos-stt-plugin-server"},
    "llm": {"persona_name": "Neon Classic", "id": "Neon Classic", "enabled": True},
}

DAY_SECONDS = 86400


def make_jwt(expires_in: float) -> str:
    """Build an unsigned JWT with the given lifetime in seconds."""

    def _b64(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    header = _b64({"alg": "HS256", "typ": "JWT"})
    payload = _b64({"exp": time.time() + expires_in, "sub": TEST_USERNAME})
    return f"{header}.{payload}.fakesignature"


def auth_payload(
    access_expires_in: float = DAY_SECONDS,
    refresh_expires_in: float = 7 * DAY_SECONDS,
) -> dict:
    """Build an /auth/login or /auth/refresh response payload."""
    return {
        "username": TEST_USERNAME,
        "client_id": "test-client-id",
        "access_token": make_jwt(access_expires_in),
        "refresh_token": make_jwt(refresh_expires_in),
        "expiration": time.time() + refresh_expires_in,
    }


def mock_hub(
    aioclient_mock: AiohttpClientMocker,
    *,
    ready: bool = True,
    access_expires_in: float = DAY_SECONDS,
) -> None:
    """Mock the hub's identity, status, and login endpoints."""
    aioclient_mock.get(f"{TEST_BASE_URL}/hub/identity", json=IDENTITY_PAYLOAD)
    aioclient_mock.get(f"{TEST_BASE_URL}/hub/config", json=HUB_CONFIG_PAYLOAD)
    aioclient_mock.get(f"{TEST_BASE_URL}/status", text="Ready" if ready else "Starting")
    aioclient_mock.post(
        f"{TEST_BASE_URL}/auth/login",
        json=auth_payload(access_expires_in=access_expires_in),
    )


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    return


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a config entry matching a successful config flow."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Neon Hub",
        unique_id=TEST_HUB_ID,
        data={
            "host": TEST_HOST,
            "username": TEST_USERNAME,
            "password": TEST_PASSWORD,
            "verify_ssl": False,
            CONF_BASE_URL: TEST_BASE_URL,
        },
    )


async def setup_integration(hass, aioclient_mock, entry) -> None:
    """Mock the hub and fully set up the given config entry."""
    # The conversation platform needs the core homeassistant integration
    # (exposed entities registry) before conversation entities can be added.
    assert await async_setup_component(hass, "homeassistant", {})
    mock_hub(aioclient_mock)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
