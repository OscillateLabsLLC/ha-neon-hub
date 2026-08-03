"""Base entity for Neon Hub."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import NeonHubCoordinator


class NeonHubEntity(CoordinatorEntity[NeonHubCoordinator]):
    """Base entity attached to the hub device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: NeonHubCoordinator, key: str) -> None:
        """Initialize the entity with a unique id derived from the hub id."""
        super().__init__(coordinator)
        identity = coordinator.data.identity
        self._attr_unique_id = f"{identity.hub_id}-{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, identity.hub_id)},
            name=identity.display_name,
            manufacturer=MANUFACTURER,
            model=MODEL,
            # The stable kebab-case hub name, surfaced on the device card.
            serial_number=identity.hub_id,
            sw_version=identity.version,
            configuration_url=coordinator.client.base_url,
        )
