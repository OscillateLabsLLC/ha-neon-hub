"""Constants for the Neon Hub integration."""

from __future__ import annotations

DOMAIN = "neon_hub"

CONF_BASE_URL = "base_url"
CONF_LLM_BACKEND = "llm_backend"
CONF_TTS_GENDER = "tts_gender"
CONF_LANG = "language"

DEFAULT_PORT = 443
# Neon Hub ships with a self-signed certificate by default.
DEFAULT_VERIFY_SSL = False
DEFAULT_LANG = "en-us"
DEFAULT_LLM_BACKEND = "chatgpt"
DEFAULT_TTS_GENDER = "female"

LLM_BACKENDS = ["chatgpt", "fastchat", "gemini", "claude", "palm"]
TTS_GENDERS = ["female", "male"]

MANUFACTURER = "Neon AI"
MODEL = "Neon Hub"

UPDATE_INTERVAL_SECONDS = 60
