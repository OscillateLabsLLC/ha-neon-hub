"""Tests for the Neon Hub TTS, STT, conversation, and sensor platforms."""

import base64
import json
from collections.abc import AsyncIterable

import aiohttp
import pytest
from homeassistant.components import stt
from homeassistant.components.conversation import ConversationInput
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_component import DATA_INSTANCES
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from .conftest import TEST_BASE_URL, setup_integration

WAV_BYTES = b"RIFF....WAVEfake-audio"
TTS_RESPONSE = {"encoded_audio": base64.b64encode(WAV_BYTES).decode()}

STT_METADATA = stt.SpeechMetadata(
    language="en-US",
    format=stt.AudioFormats.WAV,
    codec=stt.AudioCodecs.PCM,
    bit_rate=stt.AudioBitRates.BITRATE_16,
    sample_rate=stt.AudioSampleRates.SAMPLERATE_16000,
    channel=stt.AudioChannels.CHANNEL_MONO,
)


def get_entity(hass: HomeAssistant, domain: str, entity_id: str):
    entity = hass.data[DATA_INSTANCES][domain].get_entity(entity_id)
    assert entity is not None
    return entity


async def audio_stream() -> AsyncIterable[bytes]:
    yield b"\x00\x01" * 1600
    yield b"\x02\x03" * 1600


async def empty_stream() -> AsyncIterable[bytes]:
    return
    yield


def conversation_input(text: str, conversation_id: str | None) -> ConversationInput:
    return ConversationInput(
        text=text,
        context=Context(),
        conversation_id=conversation_id,
        device_id=None,
        satellite_id=None,
        language="en-US",
        agent_id="conversation.neon_hub_assistant",
    )


async def test_tts_entity(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The TTS entity synthesizes WAV audio via the hub."""
    await setup_integration(hass, aioclient_mock, mock_config_entry)
    entity = get_entity(hass, "tts", "tts.neon_hub_text_to_speech")

    # A None name breaks HA's speech manager ("TTS engine name is not set")
    assert entity.name == "Text-to-Speech"
    assert entity.default_language == "en-us"
    assert entity.supported_languages == ["en-us"]

    aioclient_mock.post(f"{TEST_BASE_URL}/neon/get_tts", json=TTS_RESPONSE)
    extension, audio = await entity.async_get_tts_audio("hello", "en-us", {})
    assert extension == "wav"
    assert audio == WAV_BYTES


async def test_tts_entity_failure_raises(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A hub failure surfaces as HomeAssistantError."""
    await setup_integration(hass, aioclient_mock, mock_config_entry)
    entity = get_entity(hass, "tts", "tts.neon_hub_text_to_speech")

    aioclient_mock.post(
        f"{TEST_BASE_URL}/neon/get_tts", exc=aiohttp.ClientError("boom")
    )
    with pytest.raises(HomeAssistantError):
        await entity.async_get_tts_audio("hello", "en-us", {})


async def test_stt_entity(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The STT entity wraps PCM in WAV and returns the first transcript."""
    await setup_integration(hass, aioclient_mock, mock_config_entry)
    entity = get_entity(hass, "stt", "stt.neon_hub_speech_to_text")

    assert entity.supported_languages == ["en-us"]
    assert entity.supported_formats == [stt.AudioFormats.WAV]
    assert entity.supported_codecs == [stt.AudioCodecs.PCM]
    assert entity.supported_bit_rates == [stt.AudioBitRates.BITRATE_16]
    assert entity.supported_sample_rates == [stt.AudioSampleRates.SAMPLERATE_16000]
    assert entity.supported_channels == [stt.AudioChannels.CHANNEL_MONO]

    aioclient_mock.post(
        f"{TEST_BASE_URL}/neon/get_stt",
        json={"transcripts": ["hello world"], "parser_data": {}},
    )
    result = await entity.async_process_audio_stream(STT_METADATA, audio_stream())
    assert result.result is stt.SpeechResultState.SUCCESS
    assert result.text == "hello world"


async def test_stt_entity_empty_stream_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """An empty audio stream produces an error result without a hub call."""
    await setup_integration(hass, aioclient_mock, mock_config_entry)
    entity = get_entity(hass, "stt", "stt.neon_hub_speech_to_text")

    result = await entity.async_process_audio_stream(STT_METADATA, empty_stream())
    assert result.result is stt.SpeechResultState.ERROR


async def test_stt_entity_hub_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Hub failures and empty transcripts produce error results."""
    await setup_integration(hass, aioclient_mock, mock_config_entry)
    entity = get_entity(hass, "stt", "stt.neon_hub_speech_to_text")

    aioclient_mock.post(
        f"{TEST_BASE_URL}/neon/get_stt", exc=aiohttp.ClientError("boom")
    )
    result = await entity.async_process_audio_stream(STT_METADATA, audio_stream())
    assert result.result is stt.SpeechResultState.ERROR

    aioclient_mock.clear_requests()
    aioclient_mock.post(
        f"{TEST_BASE_URL}/neon/get_stt", json={"transcripts": [], "parser_data": {}}
    )
    result = await entity.async_process_audio_stream(STT_METADATA, audio_stream())
    assert result.result is stt.SpeechResultState.ERROR


async def test_assistant_conversation(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The assistant agent routes utterances through the skill pipeline."""
    await setup_integration(hass, aioclient_mock, mock_config_entry)
    entity = get_entity(hass, "conversation", "conversation.neon_hub_assistant")

    assert entity.supported_languages == "*"

    aioclient_mock.post(
        f"{TEST_BASE_URL}/neon/get_response",
        json={"answer": "It is sunny.", "lang_code": "en-us"},
    )
    result = await entity.async_process(conversation_input("weather?", "conv-1"))
    assert result.response.speech["plain"]["speech"] == "It is sunny."
    assert result.conversation_id == "conv-1"

    # Regression: Assist pipelines report bare codes ("en", "en-US") but HANA
    # keys skill responses by full locale and 500s on anything else — the
    # configured integration language must be sent, not the pipeline's.
    sent = aioclient_mock.mock_calls[-1][2]
    payload = json.loads(sent) if isinstance(sent, (bytes, str)) else sent
    assert payload["lang_code"] == "en-us"


async def test_assistant_conversation_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Hub failures produce a conversation error response, not an exception."""
    await setup_integration(hass, aioclient_mock, mock_config_entry)
    entity = get_entity(hass, "conversation", "conversation.neon_hub_assistant")

    aioclient_mock.post(
        f"{TEST_BASE_URL}/neon/get_response", exc=aiohttp.ClientError("boom")
    )
    result = await entity.async_process(conversation_input("weather?", "conv-1"))
    assert result.response.error_code is not None


async def test_llm_conversation_tracks_history(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The LLM agent sends accumulated history for the same conversation."""
    await setup_integration(hass, aioclient_mock, mock_config_entry)
    entity = get_entity(hass, "conversation", "conversation.neon_hub_llm")

    aioclient_mock.post(
        f"{TEST_BASE_URL}/llm/chatgpt", json={"response": "42", "history": []}
    )

    result = await entity.async_process(conversation_input("first", "conv-9"))
    assert result.response.speech["plain"]["speech"] == "42"
    assert result.conversation_id == "conv-9"

    await entity.async_process(conversation_input("second", "conv-9"))

    sent = aioclient_mock.mock_calls[-1][2]
    payload = json.loads(sent) if isinstance(sent, (bytes, str)) else sent
    assert payload["history"] == [["user", "first"], ["llm", "42"]]


async def test_llm_conversation_generates_id_and_handles_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A missing conversation id is generated; hub errors are reported."""
    await setup_integration(hass, aioclient_mock, mock_config_entry)
    entity = get_entity(hass, "conversation", "conversation.neon_hub_llm")

    aioclient_mock.post(
        f"{TEST_BASE_URL}/llm/chatgpt", json={"response": "hi", "history": []}
    )
    result = await entity.async_process(conversation_input("hello", None))
    assert result.conversation_id

    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{TEST_BASE_URL}/llm/chatgpt", exc=aiohttp.ClientError("boom"))
    result = await entity.async_process(conversation_input("hello", "conv-2"))
    assert result.response.error_code is not None


async def test_llm_conversation_evicts_old_histories(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Histories beyond the tracked-conversation cap are evicted LRU-first."""
    await setup_integration(hass, aioclient_mock, mock_config_entry)
    entity = get_entity(hass, "conversation", "conversation.neon_hub_llm")

    aioclient_mock.post(
        f"{TEST_BASE_URL}/llm/chatgpt", json={"response": "ok", "history": []}
    )
    for index in range(17):
        await entity.async_process(conversation_input("hi", f"conv-{index}"))

    assert len(entity._histories) == 16
    assert "conv-0" not in entity._histories


async def test_sensors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The ready binary sensor and version sensor reflect coordinator data."""
    await setup_integration(hass, aioclient_mock, mock_config_entry)

    ready = hass.states.get("binary_sensor.neon_hub_ready")
    assert ready is not None
    assert ready.state == "on"

    for entity_id, expected in (
        ("sensor.neon_hub_version", "0.1.1a23"),
        ("sensor.neon_hub_tts_engine", "ovos-tts-plugin-kokoro"),
        ("sensor.neon_hub_stt_engine", "ovos-stt-plugin-server"),
        ("sensor.neon_hub_llm_persona", "Neon Classic"),
    ):
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        assert state.state == expected


async def test_device_shows_hub_id_as_serial(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The device card carries the stable kebab-case hub id."""
    await setup_integration(hass, aioclient_mock, mock_config_entry)

    device = dr.async_get(hass).async_get_device(
        identifiers={("neon_hub", "fierce-amber-node")}
    )
    assert device is not None
    assert device.serial_number == "fierce-amber-node"
    assert device.sw_version == "0.1.1a23"
    assert device.name == "Neon Hub"
