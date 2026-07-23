"""Thin Telegram Bot API client for the central PostHog bot.

Hand-rolled over ``requests`` (no SDK dependency) in the same spirit as the Twilio
provider in the workflows product. The bot token appears in every request URL
(``api.telegram.org/bot<token>/...``), so errors are sanitized before they can reach
logs or exception trackers.
"""

from datetime import timedelta
from typing import Any

from django.core.cache import cache

import requests
import structlog

from posthog.models.instance_setting import get_instance_settings

logger = structlog.get_logger(__name__)

TELEGRAM_API_BASE_URL = "https://api.telegram.org"
_REQUEST_TIMEOUT_SECONDS = 10
_BOT_IDENTITY_CACHE_KEY = "telegram_app:bot_identity"
_BOT_IDENTITY_CACHE_TTL = timedelta(hours=24)


class TelegramApiError(Exception):
    """The Telegram Bot API returned an error or the request failed."""


def telegram_config() -> dict[str, str]:
    return get_instance_settings(["TELEGRAM_APP_BOT_TOKEN", "TELEGRAM_APP_WEBHOOK_SECRET"])


class TelegramBotClient:
    def __init__(self, token: str | None = None) -> None:
        self._token = token or str(telegram_config()["TELEGRAM_APP_BOT_TOKEN"] or "")
        if not self._token:
            raise TelegramApiError("Telegram bot token is not configured")

    def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{TELEGRAM_API_BASE_URL}/bot{self._token}/{method}"
        try:
            response = requests.post(url, json=payload, timeout=_REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            # The exception message may embed the URL (and therefore the token) — keep
            # only the exception class name.
            raise TelegramApiError(f"Telegram API request failed: {type(exc).__name__} for {method}") from None
        try:
            data = response.json()
        except ValueError:
            raise TelegramApiError(f"Telegram API returned non-JSON (HTTP {response.status_code}) for {method}")
        if not response.ok or not data.get("ok"):
            raise TelegramApiError(
                f"Telegram API error for {method}: HTTP {response.status_code}, {data.get('description', 'unknown')}"
            )
        result = data.get("result")
        return result if isinstance(result, dict) else {"result": result}

    def get_me(self) -> dict[str, Any]:
        return self._call("getMe", {})

    def send_message(self, *, chat_id: str, text: str, reply_to_message_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            # Plain text on purpose: no parse_mode means no MarkdownV2 escaping failure
            # mode — a mis-escaped entity drops the whole message.
            "text": text,
            "link_preview_options": {"is_disabled": True},
        }
        if reply_to_message_id is not None:
            payload["reply_parameters"] = {
                "message_id": int(reply_to_message_id),
                "allow_sending_without_reply": True,
            }
        return self._call("sendMessage", payload)

    def set_message_reaction(self, *, chat_id: str, message_id: str, emoji: str) -> None:
        self._call(
            "setMessageReaction",
            {
                "chat_id": chat_id,
                "message_id": int(message_id),
                "reaction": [{"type": "emoji", "emoji": emoji}],
            },
        )

    def set_webhook(self, *, url: str, secret_token: str) -> None:
        self._call(
            "setWebhook",
            {
                "url": url,
                "secret_token": secret_token,
                "allowed_updates": ["message"],
            },
        )


def get_bot_identity() -> dict[str, Any]:
    """The bot's own id and username (via ``getMe``), cached per process cluster.

    Used for group @mention detection and for building ``t.me`` deep links.
    """
    cached = cache.get(_BOT_IDENTITY_CACHE_KEY)
    if isinstance(cached, dict):
        return cached
    me = TelegramBotClient().get_me()
    identity = {"id": me.get("id"), "username": me.get("username")}
    cache.set(_BOT_IDENTITY_CACHE_KEY, identity, timeout=int(_BOT_IDENTITY_CACHE_TTL.total_seconds()))
    return identity
