"""Conversation entities for Neon Hub."""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Literal

from homeassistant.components.conversation import (
    ConversationEntity,
    ConversationInput,
    ConversationResult,
)
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import ulid as ulid_util

from . import NeonHubConfigEntry
from .api import NeonHubClient, NeonHubError
from .const import CONF_LANG, CONF_LLM_BACKEND, DEFAULT_LANG, DEFAULT_LLM_BACKEND
from .entity import NeonHubEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

_MAX_TRACKED_CONVERSATIONS = 16
_MAX_HISTORY_TURNS = 20


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: NeonHubConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Neon Hub conversation entities from a config entry."""
    async_add_entities(
        [
            NeonAssistantConversationEntity(config_entry),
            NeonLlmConversationEntity(config_entry),
        ]
    )


def _error_result(user_input: ConversationInput, message: str) -> ConversationResult:
    """Build a conversation error result."""
    response = intent.IntentResponse(language=user_input.language)
    response.async_set_error(intent.IntentResponseErrorCode.UNKNOWN, message)
    return ConversationResult(
        response=response, conversation_id=user_input.conversation_id
    )


def _speech_result(user_input: ConversationInput, answer: str) -> ConversationResult:
    """Build a conversation result that speaks the given answer."""
    response = intent.IntentResponse(language=user_input.language)
    response.async_set_speech(answer)
    return ConversationResult(
        response=response, conversation_id=user_input.conversation_id
    )


class NeonConversationEntityBase(NeonHubEntity, ConversationEntity):
    """Shared behavior for Neon Hub conversation entities."""

    def __init__(self, config_entry: NeonHubConfigEntry, key: str) -> None:
        """Initialize the conversation entity."""
        super().__init__(config_entry.runtime_data.coordinator, key)
        self._client: NeonHubClient = config_entry.runtime_data.client

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """The hub handles language routing itself; accept any language."""
        return MATCH_ALL


class NeonAssistantConversationEntity(NeonConversationEntityBase):
    """Conversation agent backed by the Neon skill pipeline."""

    _attr_translation_key = "assistant"

    def __init__(self, config_entry: NeonHubConfigEntry) -> None:
        """Initialize the assistant conversation entity."""
        super().__init__(config_entry, "assistant")
        # HANA keys skill responses by full locale (e.g. "en-us") and 500s on
        # bare codes like "en", which is what Assist pipelines report — so
        # always send the configured integration language.
        self._lang: str = config_entry.options.get(CONF_LANG, DEFAULT_LANG)

    async def async_process(self, user_input: ConversationInput) -> ConversationResult:
        """Send the utterance through the Neon skill pipeline."""
        try:
            answer = await self._client.async_get_response(user_input.text, self._lang)
        except NeonHubError as err:
            _LOGGER.debug("Skill request failed", exc_info=True)
            return _error_result(user_input, f"Neon Hub request failed: {err}")
        return _speech_result(user_input, answer)


class NeonLlmConversationEntity(NeonConversationEntityBase):
    """Conversation agent backed by a hub LLM endpoint directly."""

    _attr_translation_key = "llm"

    def __init__(self, config_entry: NeonHubConfigEntry) -> None:
        """Initialize the LLM conversation entity."""
        super().__init__(config_entry, "llm")
        self._backend: str = config_entry.options.get(
            CONF_LLM_BACKEND, DEFAULT_LLM_BACKEND
        )
        # conversation_id -> [[role, content], ...] as HANA's LLMRequest expects
        self._histories: OrderedDict[str, list[list[str]]] = OrderedDict()

    def _history(self, conversation_id: str) -> list[list[str]]:
        """Return (and LRU-track) the history for a conversation."""
        history = self._histories.setdefault(conversation_id, [])
        self._histories.move_to_end(conversation_id)
        while len(self._histories) > _MAX_TRACKED_CONVERSATIONS:
            self._histories.popitem(last=False)
        return history

    async def async_process(self, user_input: ConversationInput) -> ConversationResult:
        """Send the utterance to the configured LLM backend."""
        conversation_id = user_input.conversation_id or ulid_util.ulid_now()
        history = self._history(conversation_id)

        try:
            answer = await self._client.async_llm_ask(
                self._backend, user_input.text, history
            )
        except NeonHubError as err:
            _LOGGER.debug("LLM request failed", exc_info=True)
            return _error_result(user_input, f"Neon Hub LLM request failed: {err}")

        history.append(["user", user_input.text])
        history.append(["llm", answer])
        del history[: -2 * _MAX_HISTORY_TURNS]

        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(answer)
        return ConversationResult(response=response, conversation_id=conversation_id)
