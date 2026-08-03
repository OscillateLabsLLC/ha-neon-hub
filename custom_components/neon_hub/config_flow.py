"""Config flow for Neon Hub."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from . import NeonHubConfigEntry
from .api import NeonHubAuthError, NeonHubClient, NeonHubConnectionError
from .const import (
    CONF_BASE_URL,
    CONF_LANG,
    CONF_LLM_BACKEND,
    CONF_TTS_GENDER,
    DEFAULT_LANG,
    DEFAULT_LLM_BACKEND,
    DEFAULT_TTS_GENDER,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    LLM_BACKENDS,
    TTS_GENDERS,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
    }
)

STEP_REAUTH_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_LLM_BACKEND, default=DEFAULT_LLM_BACKEND): vol.In(
            LLM_BACKENDS
        ),
        vol.Required(CONF_TTS_GENDER, default=DEFAULT_TTS_GENDER): vol.In(TTS_GENDERS),
        vol.Required(CONF_LANG, default=DEFAULT_LANG): str,
    }
)


def _build_base_url(host: str) -> str:
    """Build a base URL from a hostname or URL; defaults to HTTPS."""
    host = host.strip().rstrip("/")
    if not urlparse(host).scheme:
        host = f"https://{host}"
    return host.rstrip("/")


class NeonHubConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Neon Hub."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._discovered_host: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: NeonHubConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return NeonHubOptionsFlow()

    async def _async_validate(
        self, user_input: dict[str, Any], *, is_reauth: bool = False
    ) -> tuple[dict[str, str], dict[str, Any], str]:
        """Validate connection and credentials.

        Returns (errors, entry data, title); data and title are only
        meaningful when errors is empty.
        """
        errors: dict[str, str] = {}
        base_url = _build_base_url(user_input[CONF_HOST])
        verify_ssl = user_input.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)

        session = async_get_clientsession(self.hass, verify_ssl=verify_ssl)
        client = NeonHubClient(
            session, base_url, user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
        )

        try:
            identity = await client.async_get_identity()
        except NeonHubConnectionError:
            _LOGGER.debug("Cannot connect to hub at %s", base_url, exc_info=True)
            errors["base"] = "cannot_connect"
            return (errors, {}, "")

        await self.async_set_unique_id(identity.hub_id)
        if is_reauth:
            self._abort_if_unique_id_mismatch()
        else:
            self._abort_if_unique_id_configured()

        try:
            await client.async_login()
        except NeonHubAuthError:
            _LOGGER.debug("Hub rejected credentials", exc_info=True)
            errors["base"] = "invalid_auth"
            return (errors, {}, "")
        except NeonHubConnectionError:
            _LOGGER.debug("Cannot connect to hub at %s", base_url, exc_info=True)
            errors["base"] = "cannot_connect"
            return (errors, {}, "")

        data = {
            CONF_HOST: user_input[CONF_HOST].strip(),
            CONF_USERNAME: user_input[CONF_USERNAME],
            CONF_PASSWORD: user_input[CONF_PASSWORD],
            CONF_VERIFY_SSL: verify_ssl,
            CONF_BASE_URL: base_url,
        }
        return (errors, data, identity.display_name)

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors, data, title = await self._async_validate(user_input)
            if not errors:
                return self.async_create_entry(title=title, data=data)

        schema = STEP_USER_DATA_SCHEMA
        if self._discovered_host:
            schema = self.add_suggested_values_to_schema(
                schema, {CONF_HOST: self._discovered_host}
            )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle a hub discovered via mDNS (_neon-hub._tcp)."""
        properties = discovery_info.properties
        host = properties.get("host") or str(discovery_info.host)
        scheme = properties.get("scheme", "https")
        base_url = f"{scheme}://{host}"

        session = async_get_clientsession(self.hass, verify_ssl=DEFAULT_VERIFY_SSL)
        client = NeonHubClient(session, base_url, "", "")
        try:
            identity = await client.async_get_identity()
        except NeonHubConnectionError:
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(identity.hub_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        self._discovered_host = host
        self.context["title_placeholders"] = {"name": identity.display_name}
        return await self.async_step_user()

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle reauthentication when the hub rejects stored credentials."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Collect new credentials for an existing entry."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            errors, data, _ = await self._async_validate(
                {**reauth_entry.data, **user_input}, is_reauth=True
            )
            if not errors:
                return self.async_update_reload_and_abort(
                    reauth_entry, data_updates=data
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle reconfiguration of the integration."""
        errors: dict[str, str] = {}
        reconfigure_entry = self._get_reconfigure_entry()

        if user_input is not None:
            errors, data, title = await self._async_validate(user_input, is_reauth=True)
            if not errors:
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    data_updates=data,
                    title=title,
                )

        suggested_values: dict[str, Any] = {
            **reconfigure_entry.data,
            **(user_input or {}),
        }

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, suggested_values
            ),
            errors=errors,
        )


class NeonHubOptionsFlow(OptionsFlow):
    """Handle Neon Hub options."""

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Manage integration options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, dict(self.config_entry.options)
            ),
        )
