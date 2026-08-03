"""Binary sensor for Neon Hub readiness."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import NeonHubConfigEntry
from .entity import NeonHubEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: NeonHubConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Neon Hub binary sensor from a config entry."""
    async_add_entities([NeonHubReadyBinarySensor(config_entry)])


class NeonHubReadyBinarySensor(NeonHubEntity, BinarySensorEntity):
    """Reports whether the hub API is ready."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "ready"

    def __init__(self, config_entry: NeonHubConfigEntry) -> None:
        """Initialize the binary sensor."""
        super().__init__(config_entry.runtime_data.coordinator, "ready")

    @property
    def is_on(self) -> bool:
        """Return True when the hub reports ready."""
        return self.coordinator.data.ready
