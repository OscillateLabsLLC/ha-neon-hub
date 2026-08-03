"""Async client for the Neon Hub (HANA) HTTP API."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import time
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

QUICK_TIMEOUT = aiohttp.ClientTimeout(total=10)
# Skill and LLM responses can block on inference for a while.
VOICE_TIMEOUT = aiohttp.ClientTimeout(total=60)

# Refresh the access token this many seconds before it expires. HANA responds
# 500 (not 401) to an expired access token, so proactive refresh is load-bearing.
ACCESS_TOKEN_HORIZON = 60

TOKEN_NAME = "Home Assistant"

_AUTH_STATUSES = {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}
_MAX_AUTH_ATTEMPTS = 2


class NeonHubError(Exception):
    """Base error for the Neon Hub client."""


class NeonHubConnectionError(NeonHubError):
    """The hub could not be reached or returned an unexpected response."""


class NeonHubAuthError(NeonHubError):
    """Authentication with the hub failed."""


@dataclass(slots=True)
class HubIdentity:
    """Identity reported by GET /hub/identity."""

    hub_id: str
    display_name: str
    version: str
    warning: str | None = None


@dataclass(slots=True)
class HubConfig:
    """Active service identifiers reported by GET /hub/config."""

    tts_module: str | None = None
    stt_module: str | None = None
    llm_persona: str | None = None


def _jwt_expiration(token: str) -> float:
    """Extract the exp claim from a JWT without verifying its signature.

    The client only needs the expiration to schedule refreshes; validation
    is the hub's job. Returns 0 for malformed tokens so they refresh eagerly.
    """
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return float(payload["exp"])
    except (IndexError, KeyError, ValueError, TypeError, binascii.Error):
        _LOGGER.debug("Could not decode JWT expiration; treating as expired")
        return 0


class NeonHubClient:
    """Client for a single Neon Hub (HANA) instance."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        username: str,
        password: str,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._base_url = base_url
        self._username = username
        self._password = password
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._client_id: str | None = None
        self._access_expiration: float = 0
        self._refresh_expiration: float = 0
        # Serializes login/refresh so concurrent requests cannot burn the
        # hub's auth rate limit (6 requests/minute).
        self._auth_lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        """Return the hub base URL."""
        return self._base_url

    # ---------------------------------------------------------------- auth

    async def async_login(self) -> None:
        """Authenticate with username/password and store tokens."""
        data = await self._post_unauthenticated(
            "/auth/login",
            {
                "username": self._username,
                "password": self._password,
                "token_name": TOKEN_NAME,
            },
            auth_request=True,
        )
        self._store_tokens(data)

    async def _async_refresh(self) -> None:
        """Exchange the refresh token for a new token pair."""
        data = await self._post_unauthenticated(
            "/auth/refresh",
            {
                "access_token": self._access_token,
                "refresh_token": self._refresh_token,
                "client_id": self._client_id,
            },
            auth_request=True,
        )
        self._store_tokens(data)

    def _store_tokens(self, data: dict[str, Any]) -> None:
        try:
            self._access_token = data["access_token"]
            self._refresh_token = data["refresh_token"]
            self._client_id = data["client_id"]
        except KeyError as err:
            raise NeonHubConnectionError(
                f"Malformed authentication response: missing {err}"
            ) from err
        self._access_expiration = _jwt_expiration(self._access_token or "")
        self._refresh_expiration = _jwt_expiration(self._refresh_token or "")

    def _invalidate_tokens(self) -> None:
        self._access_token = None
        self._refresh_token = None
        self._access_expiration = 0
        self._refresh_expiration = 0

    async def _async_ensure_token(self) -> str:
        """Return a valid access token, refreshing or re-logging-in as needed.

        Checks BOTH token expirations: refreshing only when the refresh token
        nears expiry leaves an expired access token in play.
        """
        async with self._auth_lock:
            now = time.time()
            if self._access_token and now < (
                self._access_expiration - ACCESS_TOKEN_HORIZON
            ):
                return self._access_token
            if self._refresh_token and now < (
                self._refresh_expiration - ACCESS_TOKEN_HORIZON
            ):
                try:
                    await self._async_refresh()
                except NeonHubAuthError:
                    _LOGGER.debug("Token refresh rejected; falling back to login")
                    await self.async_login()
            else:
                await self.async_login()
            if self._access_token is None:
                raise NeonHubAuthError("Authentication produced no access token")
            return self._access_token

    # ------------------------------------------------------------ transport

    async def _post_unauthenticated(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        auth_request: bool = False,
    ) -> dict[str, Any]:
        try:
            async with self._session.post(
                f"{self._base_url}{path}", json=payload, timeout=QUICK_TIMEOUT
            ) as resp:
                if auth_request and HTTPStatus.BAD_REQUEST <= resp.status < 500:  # noqa: PLR2004
                    raise NeonHubAuthError(
                        f"Authentication failed with HTTP {resp.status}"
                    )
                resp.raise_for_status()
                result: dict[str, Any] = await resp.json()
                return result
        except (aiohttp.ClientError, TimeoutError) as err:
            raise NeonHubConnectionError(f"Cannot reach hub: {err}") from err

    async def _post_authenticated(
        self,
        path: str,
        payload: dict[str, Any],
        timeout: aiohttp.ClientTimeout,
    ) -> dict[str, Any]:
        """POST with a bearer token, retrying once after a fresh login on 401/403."""
        token = await self._async_ensure_token()
        for attempt in range(1, _MAX_AUTH_ATTEMPTS + 1):
            try:
                async with self._session.post(
                    f"{self._base_url}{path}",
                    json=payload,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=timeout,
                ) as resp:
                    if resp.status in _AUTH_STATUSES:
                        if attempt == _MAX_AUTH_ATTEMPTS:
                            raise NeonHubAuthError(
                                f"Hub rejected credentials for {path}"
                            )
                        self._invalidate_tokens()
                        token = await self._async_ensure_token()
                        continue
                    resp.raise_for_status()
                    result: dict[str, Any] = await resp.json()
                    return result
            except (aiohttp.ClientError, TimeoutError) as err:
                raise NeonHubConnectionError(f"Cannot reach hub: {err}") from err
        raise NeonHubConnectionError("Unreachable retry state")  # pragma: no cover

    # ------------------------------------------------------------ endpoints

    async def async_get_identity(self) -> HubIdentity:
        """Fetch hub identity (unauthenticated endpoint)."""
        try:
            async with self._session.get(
                f"{self._base_url}/hub/identity", timeout=QUICK_TIMEOUT
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise NeonHubConnectionError(f"Cannot reach hub: {err}") from err
        try:
            return HubIdentity(
                hub_id=data["hub_id"],
                display_name=data["display_name"],
                version=data["version"],
                warning=data.get("warning"),
            )
        except (KeyError, TypeError) as err:
            raise NeonHubConnectionError(f"Malformed identity response: {err}") from err

    async def async_get_hub_config(self) -> HubConfig:
        """Fetch active TTS/STT/LLM identifiers (unauthenticated endpoint)."""
        try:
            async with self._session.get(
                f"{self._base_url}/hub/config", timeout=QUICK_TIMEOUT
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise NeonHubConnectionError(f"Cannot reach hub: {err}") from err
        if not isinstance(data, dict):
            return HubConfig()

        def module_of(section: str) -> str | None:
            value = data.get(section)
            return value.get("module") if isinstance(value, dict) else None

        llm = data.get("llm")
        persona = None
        if isinstance(llm, dict):
            persona = llm.get("persona_name") or llm.get("id")
        return HubConfig(
            tts_module=module_of("tts"),
            stt_module=module_of("stt"),
            llm_persona=persona,
        )

    async def async_check_ready(self) -> bool:
        """Return True if GET /status reports the hub is ready."""
        try:
            async with self._session.get(
                f"{self._base_url}/status", timeout=QUICK_TIMEOUT
            ) as resp:
                resp.raise_for_status()
                # /status returns plain text ("Ready"), not JSON.
                return "ready" in (await resp.text()).strip().lower()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise NeonHubConnectionError(f"Cannot reach hub: {err}") from err

    async def async_get_tts(self, text: str, lang_code: str, gender: str) -> bytes:
        """Synthesize speech; returns WAV audio bytes."""
        data = await self._post_authenticated(
            "/neon/get_tts",
            {"to_speak": text, "lang_code": lang_code, "gender": gender},
            VOICE_TIMEOUT,
        )
        try:
            return base64.b64decode(data["encoded_audio"])
        except (KeyError, TypeError, binascii.Error) as err:
            raise NeonHubConnectionError(f"Malformed TTS response: {err}") from err

    async def async_get_stt(self, wav_audio: bytes, lang_code: str) -> list[str]:
        """Transcribe WAV audio; returns candidate transcripts."""
        data = await self._post_authenticated(
            "/neon/get_stt",
            {
                "encoded_audio": base64.b64encode(wav_audio).decode(),
                "lang_code": lang_code,
            },
            VOICE_TIMEOUT,
        )
        transcripts = data.get("transcripts")
        if not isinstance(transcripts, list):
            raise NeonHubConnectionError("Malformed STT response: no transcripts")
        return [str(t) for t in transcripts]

    async def async_get_response(self, utterance: str, lang_code: str) -> str:
        """Send an utterance through the Neon skill pipeline; returns the answer."""
        data = await self._post_authenticated(
            "/neon/get_response",
            {"utterance": utterance, "lang_code": lang_code},
            VOICE_TIMEOUT,
        )
        answer = data.get("answer")
        if not isinstance(answer, str):
            raise NeonHubConnectionError("Malformed skill response: no answer")
        return answer

    async def async_llm_ask(
        self, backend: str, query: str, history: list[list[str]]
    ) -> str:
        """Query an LLM backend directly; returns the response text."""
        data = await self._post_authenticated(
            f"/llm/{backend}",
            # Snapshot: callers keep appending to their history list.
            {"query": query, "history": list(history)},
            VOICE_TIMEOUT,
        )
        response = data.get("response")
        if not isinstance(response, str):
            raise NeonHubConnectionError("Malformed LLM response")
        return response
