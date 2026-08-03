"""STT entity for Neon Hub."""

from __future__ import annotations

import io
import logging
import wave
from collections.abc import AsyncIterable

from homeassistant.components.stt import (
    AudioBitRates,
    AudioChannels,
    AudioCodecs,
    AudioFormats,
    AudioSampleRates,
    SpeechMetadata,
    SpeechResult,
    SpeechResultState,
    SpeechToTextEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import NeonHubConfigEntry
from .api import NeonHubError
from .const import CONF_LANG, DEFAULT_LANG
from .entity import NeonHubEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

_SAMPLE_WIDTH_BYTES = 2


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: NeonHubConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Neon Hub STT entity from a config entry."""
    async_add_entities([NeonHubSttEntity(config_entry)])


def _pcm_to_wav(pcm: bytes, sample_rate: int, channels: int) -> bytes:
    """Wrap raw 16-bit PCM audio in a WAV container."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(_SAMPLE_WIDTH_BYTES)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm)
    return buffer.getvalue()


class NeonHubSttEntity(NeonHubEntity, SpeechToTextEntity):
    """Neon Hub speech-to-text entity."""

    _attr_translation_key = "stt"

    def __init__(self, config_entry: NeonHubConfigEntry) -> None:
        """Initialize the STT entity."""
        super().__init__(config_entry.runtime_data.coordinator, "stt")
        self._client = config_entry.runtime_data.client
        self._lang: str = config_entry.options.get(CONF_LANG, DEFAULT_LANG)

    @property
    def supported_languages(self) -> list[str]:
        """Return the configured language."""
        return [self._lang]

    @property
    def supported_formats(self) -> list[AudioFormats]:
        """Return supported audio formats."""
        return [AudioFormats.WAV]

    @property
    def supported_codecs(self) -> list[AudioCodecs]:
        """Return supported audio codecs."""
        return [AudioCodecs.PCM]

    @property
    def supported_bit_rates(self) -> list[AudioBitRates]:
        """Return supported bit rates."""
        return [AudioBitRates.BITRATE_16]

    @property
    def supported_sample_rates(self) -> list[AudioSampleRates]:
        """Return supported sample rates."""
        return [AudioSampleRates.SAMPLERATE_16000]

    @property
    def supported_channels(self) -> list[AudioChannels]:
        """Return supported channel counts."""
        return [AudioChannels.CHANNEL_MONO]

    async def async_process_audio_stream(
        self, metadata: SpeechMetadata, stream: AsyncIterable[bytes]
    ) -> SpeechResult:
        """Collect the audio stream and transcribe it via the hub."""
        pcm = b"".join([chunk async for chunk in stream])
        if not pcm:
            return SpeechResult(None, SpeechResultState.ERROR)

        wav_audio = _pcm_to_wav(pcm, int(metadata.sample_rate), int(metadata.channel))

        try:
            transcripts = await self._client.async_get_stt(
                wav_audio, metadata.language.lower()
            )
        except NeonHubError:
            _LOGGER.debug("Transcription request failed", exc_info=True)
            return SpeechResult(None, SpeechResultState.ERROR)

        if not transcripts:
            return SpeechResult(None, SpeechResultState.ERROR)
        return SpeechResult(transcripts[0], SpeechResultState.SUCCESS)
