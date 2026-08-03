"""Tests for Neon Hub diagnostics."""

from homeassistant.components.diagnostics import REDACTED
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.neon_hub.diagnostics import async_get_config_entry_diagnostics

from .conftest import setup_integration


async def test_diagnostics_redacts_secrets(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Diagnostics include hub state and redact host and credentials."""
    await setup_integration(hass, aioclient_mock, mock_config_entry)

    diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    assert diagnostics["entry_data"]["host"] == REDACTED
    assert diagnostics["entry_data"]["base_url"] == REDACTED
    assert diagnostics["entry_data"]["username"] == REDACTED
    assert diagnostics["entry_data"]["password"] == REDACTED
    assert diagnostics["hub_state"]["identity"]["hub_id"] == "fierce-amber-node"
    assert diagnostics["hub_state"]["ready"] is True
    assert diagnostics["last_update_success"] is True
