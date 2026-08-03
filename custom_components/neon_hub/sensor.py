"""Sensors for Neon Hub."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import NeonHubConfigEntry
from .coordinator import HubState
from .entity import NeonHubEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class NeonHubSensorDescription(SensorEntityDescription):
    """Describes a Neon Hub sensor."""

    value_fn: Callable[[HubState], str | None]


SENSORS: tuple[NeonHubSensorDescription, ...] = (
    NeonHubSensorDescription(
        key="version",
        translation_key="version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.identity.version,
    ),
    NeonHubSensorDescription(
        key="tts_engine",
        translation_key="tts_engine",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.config.tts_module,
    ),
    NeonHubSensorDescription(
        key="stt_engine",
        translation_key="stt_engine",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.config.stt_module,
    ),
    NeonHubSensorDescription(
        key="llm_persona",
        translation_key="llm_persona",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.config.llm_persona,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: NeonHubConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Neon Hub sensors from a config entry."""
    async_add_entities(
        NeonHubSensor(config_entry, description) for description in SENSORS
    )


class NeonHubSensor(NeonHubEntity, SensorEntity):
    """A hub state value surfaced as a diagnostic sensor."""

    entity_description: NeonHubSensorDescription

    def __init__(
        self,
        config_entry: NeonHubConfigEntry,
        description: NeonHubSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(config_entry.runtime_data.coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> str | None:
        """Return the described hub state value."""
        return self.entity_description.value_fn(self.coordinator.data)
