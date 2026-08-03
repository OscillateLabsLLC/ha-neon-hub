"""TTS entity for Neon Hub."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.tts import TextToSpeechEntity, TtsAudioType
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import NeonHubConfigEntry
from .api import NeonHubError
from .const import (
    CONF_LANG,
    CONF_TTS_GENDER,
    DEFAULT_LANG,
    DEFAULT_TTS_GENDER,
    DOMAIN,
)
from .entity import NeonHubEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: NeonHubConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Neon Hub TTS entity from a config entry."""
    async_add_entities([NeonHubTtsEntity(config_entry)])


class NeonHubTtsEntity(NeonHubEntity, TextToSpeechEntity):
    """Neon Hub text-to-speech entity."""

    # NOTE: TTS entities must have a non-None name (the speech manager uses it
    # as the cache key), so device-name inheritance via _attr_name = None does
    # not work here; use a translated entity name instead.
    _attr_translation_key = "tts"

    def __init__(self, config_entry: NeonHubConfigEntry) -> None:
        """Initialize the TTS entity."""
        super().__init__(config_entry.runtime_data.coordinator, "tts")
        self._client = config_entry.runtime_data.client
        self._gender: str = config_entry.options.get(
            CONF_TTS_GENDER, DEFAULT_TTS_GENDER
        )
        lang: str = config_entry.options.get(CONF_LANG, DEFAULT_LANG)
        self._attr_default_language = lang
        self._attr_supported_languages = [lang]

    async def async_get_tts_audio(
        self, message: str, language: str, options: dict[str, Any]
    ) -> TtsAudioType:
        """Synthesize speech via the hub."""
        try:
            audio = await self._client.async_get_tts(message, language, self._gender)
        except NeonHubError as err:
            _LOGGER.debug("Speech synthesis request failed", exc_info=True)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="synthesize_failed",
            ) from err
        return ("wav", audio)
