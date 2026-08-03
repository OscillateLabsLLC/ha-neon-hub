"""Tests for Neon Hub setup and unload."""

import aiohttp
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from .conftest import TEST_BASE_URL, auth_payload, setup_integration


async def test_setup_and_unload(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A reachable hub sets up all platforms and unloads cleanly."""
    await setup_integration(hass, aioclient_mock, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    for entity_id in (
        "tts.neon_hub_text_to_speech",
        "stt.neon_hub_speech_to_text",
        "conversation.neon_hub_assistant",
        "conversation.neon_hub_llm",
        "binary_sensor.neon_hub_ready",
        "sensor.neon_hub_version",
        "sensor.neon_hub_tts_engine",
        "sensor.neon_hub_stt_engine",
        "sensor.neon_hub_llm_persona",
    ):
        assert hass.states.get(entity_id) is not None, entity_id

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_retries_when_hub_down(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """An unreachable hub raises ConfigEntryNotReady (setup retry)."""
    aioclient_mock.post(f"{TEST_BASE_URL}/auth/login", exc=aiohttp.ClientError("boom"))
    mock_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_starts_reauth_on_bad_credentials(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Rejected credentials during setup raise ConfigEntryAuthFailed."""
    aioclient_mock.post(f"{TEST_BASE_URL}/auth/login", status=404)
    mock_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR

    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == "reauth" for flow in flows)


async def test_setup_retries_when_identity_fails(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Login succeeding but the first coordinator poll failing retries setup."""
    aioclient_mock.post(f"{TEST_BASE_URL}/auth/login", json=auth_payload())
    aioclient_mock.get(f"{TEST_BASE_URL}/hub/identity", exc=aiohttp.ClientError("boom"))

    mock_config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_options_update_reloads_entry(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Changing options reloads the config entry."""
    await setup_integration(hass, aioclient_mock, mock_config_entry)

    hass.config_entries.async_update_entry(
        mock_config_entry, options={"llm_backend": "gemini"}
    )
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
