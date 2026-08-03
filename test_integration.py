"""Live end-to-end validation against a real Neon Hub.

Not part of the pytest suite. Exercises the actual API client against real
hub behavior that mocks structurally cannot catch (auth flows, response
shapes, timeouts, TLS).

Usage:
    NEON_HUB_USERNAME=... NEON_HUB_PASSWORD=... uv run python test_integration.py

Environment variables:
    NEON_HUB_URL       Hub base URL (default: https://hana.neon-hub.local)
    NEON_HUB_USERNAME  Hub account username (required)
    NEON_HUB_PASSWORD  Hub account password (required)
    NEON_HUB_LLM       LLM backend to test (default: chatgpt; "skip" to skip)
"""

import asyncio
import io
import os
import sys
import wave

import aiohttp

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from custom_components.neon_hub.api import (
    NeonHubClient,
    NeonHubError,
)
from custom_components.neon_hub.stt import _pcm_to_wav

BASE_URL = os.environ.get("NEON_HUB_URL", "https://hana.neon-hub.local")
USERNAME = os.environ.get("NEON_HUB_USERNAME")
PASSWORD = os.environ.get("NEON_HUB_PASSWORD")
LLM_BACKEND = os.environ.get("NEON_HUB_LLM", "chatgpt")

PASSED = []
FAILED = []


def report(name: str, ok: bool, detail: str = "") -> None:
    (PASSED if ok else FAILED).append(name)
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> int:
    if not USERNAME or not PASSWORD:
        print("Set NEON_HUB_USERNAME and NEON_HUB_PASSWORD first.")
        return 2

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        client = NeonHubClient(session, BASE_URL, USERNAME, PASSWORD)

        print(f"Target: {BASE_URL}")

        identity = await client.async_get_identity()
        report(
            "identity", bool(identity.hub_id), f"{identity.hub_id} v{identity.version}"
        )

        ready = await client.async_check_ready()
        report("status", ready, "Ready" if ready else "not ready")

        await client.async_login()
        report("login", True)

        # Force the proactive-refresh path by pretending the access token is stale.
        client._access_expiration = 0
        wav = await client.async_get_tts("Hello from Home Assistant", "en-us", "female")
        report("tts + token refresh", wav[:4] == b"RIFF", f"{len(wav)} bytes WAV")

        # Round-trip: transcribe the audio we just synthesized.
        try:
            transcripts = await client.async_get_stt(wav, "en-us")
            joined = " | ".join(transcripts) or "(empty)"
            report(
                "stt round-trip", any("hello" in t.lower() for t in transcripts), joined
            )
        except NeonHubError as err:
            report("stt round-trip", False, str(err))

        try:
            answer = await client.async_get_response("what time is it", "en-us")
            report("skill get_response", bool(answer), answer[:80])
        except NeonHubError as err:
            report("skill get_response", False, str(err))

        if LLM_BACKEND != "skip":
            try:
                answer = await client.async_llm_ask(
                    LLM_BACKEND, "Reply with the single word: pong", []
                )
                report(f"llm ({LLM_BACKEND})", bool(answer), answer[:80])
            except NeonHubError as err:
                report(f"llm ({LLM_BACKEND})", False, f"{err} (backend deployed?)")

        # Sanity-check our PCM->WAV helper output parses as valid WAV.
        packed = _pcm_to_wav(b"\x00\x01" * 16000, 16000, 1)
        with wave.open(io.BytesIO(packed)) as parsed:
            ok = parsed.getframerate() == 16000 and parsed.getnchannels() == 1
        report("pcm->wav helper", ok)

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
