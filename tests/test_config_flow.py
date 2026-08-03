"""Tests for the Neon Hub config flow."""

import aiohttp
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.neon_hub.const import DOMAIN

from .conftest import (
    IDENTITY_PAYLOAD,
    TEST_BASE_URL,
    TEST_HOST,
    TEST_PASSWORD,
    TEST_USERNAME,
    auth_payload,
    mock_hub,
    setup_integration,
)

USER_INPUT = {
    "host": TEST_HOST,
    "username": TEST_USERNAME,
    "password": TEST_PASSWORD,
    "verify_ssl": False,
}

ZEROCONF_INFO = ZeroconfServiceInfo(
    ip_address="192.168.1.50",
    ip_addresses=["192.168.1.50"],
    hostname="neon-hub.local.",
    name="Neon Hub on neon-hub._neon-hub._tcp.local.",
    port=443,
    properties={"scheme": "https", "host": TEST_HOST},
    type="_neon-hub._tcp.local.",
)


async def test_user_flow_success(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A reachable hub with valid credentials creates an entry."""
    mock_hub(aioclient_mock)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Neon Hub"
    assert result["data"]["base_url"] == TEST_BASE_URL
    assert result["data"]["username"] == TEST_USERNAME
    assert result["result"].unique_id == IDENTITY_PAYLOAD["hub_id"]


async def test_user_flow_cannot_connect_then_recovers(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An unreachable hub shows an error, then succeeds after recovery."""
    aioclient_mock.get(f"{TEST_BASE_URL}/hub/identity", exc=aiohttp.ClientError("boom"))

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    aioclient_mock.clear_requests()
    mock_hub(aioclient_mock)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_invalid_auth(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Rejected credentials show an invalid_auth error."""
    aioclient_mock.get(f"{TEST_BASE_URL}/hub/identity", json=IDENTITY_PAYLOAD)
    aioclient_mock.post(f"{TEST_BASE_URL}/auth/login", status=404)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_login_connection_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Identity reachable but login transport failure shows cannot_connect."""
    aioclient_mock.get(f"{TEST_BASE_URL}/hub/identity", json=IDENTITY_PAYLOAD)
    aioclient_mock.post(f"{TEST_BASE_URL}/auth/login", exc=aiohttp.ClientError("boom"))

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_already_configured(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A hub with an already-configured hub_id aborts."""
    mock_config_entry.add_to_hass(hass)
    mock_hub(aioclient_mock)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_zeroconf_flow_success(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A discovered hub prefills the host and creates an entry."""
    mock_hub(aioclient_mock)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=ZEROCONF_INFO,
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == IDENTITY_PAYLOAD["hub_id"]


async def test_zeroconf_flow_unreachable_aborts(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A discovered hub that does not answer identity aborts the flow."""
    aioclient_mock.get(f"{TEST_BASE_URL}/hub/identity", exc=aiohttp.ClientError("boom"))

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=ZEROCONF_INFO,
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_zeroconf_flow_already_configured(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Discovery of an already-configured hub aborts."""
    mock_config_entry.add_to_hass(hass)
    mock_hub(aioclient_mock)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=ZEROCONF_INFO,
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Reauth accepts new credentials and updates the entry."""
    await setup_integration(hass, aioclient_mock, mock_config_entry)

    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": TEST_USERNAME, "password": "new-password"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data["password"] == "new-password"


async def test_reauth_flow_invalid_auth(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Reauth with still-bad credentials keeps showing the form."""
    await setup_integration(hass, aioclient_mock, mock_config_entry)

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{TEST_BASE_URL}/hub/identity", json=IDENTITY_PAYLOAD)
    aioclient_mock.post(f"{TEST_BASE_URL}/auth/login", status=404)

    result = await mock_config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": TEST_USERNAME, "password": "still-bad"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reconfigure_flow(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Reconfigure updates connection settings for the same hub."""
    await setup_integration(hass, aioclient_mock, mock_config_entry)

    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, "verify_ssl": True}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data["verify_ssl"] is True


async def test_reconfigure_flow_different_hub_aborts(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Pointing reconfigure at a different hub aborts with a mismatch."""
    await setup_integration(hass, aioclient_mock, mock_config_entry)

    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"{TEST_BASE_URL}/hub/identity",
        json={**IDENTITY_PAYLOAD, "hub_id": "other-hub"},
    )
    aioclient_mock.post(f"{TEST_BASE_URL}/auth/login", json=auth_payload())

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unique_id_mismatch"


async def test_options_flow(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Options flow stores LLM backend, gender, and language."""
    await setup_integration(hass, aioclient_mock, mock_config_entry)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"llm_backend": "gemini", "tts_gender": "male", "language": "en-us"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options["llm_backend"] == "gemini"
