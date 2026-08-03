# Neon Hub for Home Assistant

[![Status: Proof of Concept](https://img.shields.io/badge/status-proof--of--concept-orange)](https://github.com/OscillateLabsLLC/.github/blob/main/SUPPORT_STATUS.md)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-blue)](LICENSE)

A Home Assistant custom integration for [Neon Hub](https://neon.ai), the
self-hosted voice assistant appliance. It connects to the hub's HANA HTTP API
and exposes the hub's voice and language services as native Home Assistant
entities:

| Entity | Platform | What it does |
| --- | --- | --- |
| Text-to-Speech | `tts` | Speech synthesis through the hub's TTS engine |
| Speech-to-Text | `stt` | Transcription through the hub's STT engine |
| Assistant | `conversation` | Conversation agent backed by the full Neon skill pipeline (weather, timers, skills, LLM fallback) |
| LLM | `conversation` | Conversation agent that queries a hub LLM endpoint directly |
| Ready | `binary_sensor` | Hub API readiness (diagnostic) |
| Version | `sensor` | HANA software version (diagnostic) |

The TTS, STT, and conversation entities can be combined into a full
[Assist](https://www.home-assistant.io/voice_control/) voice pipeline, so your
Home Assistant voice satellites talk to your own Neon Hub — no cloud involved.

## Requirements

- A running Neon Hub reachable from Home Assistant (HANA API, typically at
  `https://hana.<hub-hostname>` on your LAN)
- A hub user account (username + password). The integration authenticates via
  HANA's JWT flow and manages access/refresh tokens automatically.
- Home Assistant 2025.2 or newer

## Installation

### HACS (recommended)

1. In HACS, add this repository as a custom repository
   (category: Integration).
2. Install **Neon Hub**.
3. Restart Home Assistant.

### Manual

Copy `custom_components/neon_hub/` into your Home Assistant
`config/custom_components/` directory and restart Home Assistant.

## Configuration

If your hub advertises itself via mDNS (`_neon-hub._tcp`), Home Assistant will
discover it and prompt you to finish setup. Otherwise add it manually:
**Settings → Devices & Services → Add Integration → Neon Hub**.

| Parameter | Description |
| --- | --- |
| Host | Hostname or full address of the HANA API, e.g. `hana.neon-hub.local` |
| Username | Hub user account for Home Assistant |
| Password | Password for that account |
| Verify SSL certificate | Off by default — Neon Hub ships with a self-signed certificate. Enable if you have installed a real certificate. |

### Options

**Settings → Devices & Services → Neon Hub → Configure**

| Option | Default | Description |
| --- | --- | --- |
| LLM backend | `chatgpt` | Which hub LLM endpoint the LLM conversation agent uses (`chatgpt`, `fastchat`, `gemini`, `claude`, `palm`). The corresponding service must be deployed on your hub. |
| TTS voice gender | `female` | Preferred synthesis voice gender |
| Language | `en-us` | Language code used for speech services |

## How data is updated

Voice and conversation requests are made on demand. The hub's identity and
readiness are polled every 60 seconds from unauthenticated endpoints; the
diagnostic entities and entity availability derive from that poll.

Authentication is fully automatic: the integration logs in with your
credentials, refreshes the access token before it expires, falls back to a
fresh login when the refresh token lapses, and starts a reauthentication flow
if the hub rejects the credentials outright.

## Example: Neon-powered Assist pipeline

Turn the hub into a full Home Assistant voice assistant:

1. Set up this integration.
2. Go to **Settings → Voice assistants → Add assistant**.
3. Name it (e.g. "Neon") and pick the Neon Hub engines:
   - **Conversation agent**: *Neon Hub Assistant* (full skill pipeline:
     weather, timers, music, LLM fallback) or *Neon Hub LLM* (direct LLM
     chat with per-conversation history)
   - **Speech-to-text**: *Neon Hub Speech-to-Text*
   - **Text-to-speech**: *Neon Hub Text-to-Speech*
4. Verify end-to-end by opening the Assist dialog and using the microphone
   button in your browser — that exercises STT, the conversation agent, and
   TTS in one round trip.

The assistant then works from Assist satellites, the mobile apps, and the
Assist dialog. The pipeline's language should match the integration's
configured language (default `en-us`).

Or use the TTS entity directly in an automation:

```yaml
action: tts.speak
target:
  entity_id: tts.neon_hub_text_to_speech
data:
  media_player_entity_id: media_player.living_room
  message: "The wash cycle is done."
```

## Known limitations

- The LLM conversation agent requires the selected LLM service to actually be
  deployed on your hub; the hub accepts the request either way and times out
  (~60 s) if no backend consumes it.
- Speech services use the single configured language; per-call language
  switching is not supported.
- Conversation history for the LLM agent is kept in memory and resets when
  Home Assistant restarts.

## Troubleshooting

- **Cannot connect during setup** — verify the host: `curl -k
  https://<host>/hub/identity` should return JSON. Port 80 redirects to 443.
- **Invalid auth** — the account must exist in the hub's user service.
  Check the credentials against the hub's login directly.
- **Everything unavailable** — the hub stopped answering its status endpoint;
  check the `binary_sensor` and the hub's containers.
- Enable debug logging: **Settings → Devices & Services → Neon Hub →
  Enable debug logging**, or:

```yaml
logger:
  logs:
    custom_components.neon_hub: debug
```

## Removal

1. **Settings → Devices & Services → Neon Hub → Delete**.
2. If installed via HACS, remove the repository from HACS.
3. Optionally delete the hub user account used by Home Assistant.

## Development

```bash
uv sync
uv run pytest --cov     # unit tests
uv run ruff check .
uv run mypy
# live validation against a real hub:
NEON_HUB_USERNAME=... NEON_HUB_PASSWORD=... uv run python test_integration.py
```

## License

[BSD-3-Clause](LICENSE) © Oscillate Labs LLC
