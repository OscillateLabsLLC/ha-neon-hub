"""Data update coordinator for Neon Hub."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import HubConfig, HubIdentity, NeonHubClient, NeonHubConnectionError
from .const import DOMAIN, UPDATE_INTERVAL_SECONDS

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class HubState:
    """Hub state polled from the unauthenticated identity/status endpoints."""

    identity: HubIdentity
    ready: bool
    config: HubConfig


class NeonHubCoordinator(DataUpdateCoordinator[HubState]):
    """Polls hub identity and readiness."""

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: NeonHubClient
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )
        self.client = client

    async def _async_update_data(self) -> HubState:
        """Fetch identity and readiness from the hub."""
        try:
            identity = await self.client.async_get_identity()
            ready = await self.client.async_check_ready()
            config = await self.client.async_get_hub_config()
        except NeonHubConnectionError as err:
            raise UpdateFailed(str(err)) from err
        return HubState(identity=identity, ready=ready, config=config)
