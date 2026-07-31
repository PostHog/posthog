"""Thin WhatsApp Business Cloud API client for the central PostHog number.

Hand-rolled over ``requests`` (no SDK dependency), like the Telegram client. The
access token travels in the Authorization header, but exception messages from
``requests`` can still embed request details — errors are sanitized to the exception
class name before they can reach logs or exception trackers.
"""

import re
from datetime import timedelta
from typing import Any

from django.core.cache import cache

import requests
import structlog

from posthog.models.instance_setting import get_instance_settings

logger = structlog.get_logger(__name__)

GRAPH_API_BASE_URL = "https://graph.facebook.com/v23.0"
_REQUEST_TIMEOUT_SECONDS = 10
_BOT_PHONE_CACHE_KEY = "whatsapp_app:bot_phone_number"
_BOT_PHONE_CACHE_TTL = timedelta(hours=24)

# Free-form (non-template) messages are only deliverable inside the 24-hour customer
# service window that the user's last inbound message opened.
WINDOW_CLOSED_ERROR_CODE = 131047


class WhatsAppApiError(Exception):
    """The WhatsApp Cloud API returned an error or the request failed."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code

    @property
    def is_window_closed(self) -> bool:
        return self.code == WINDOW_CLOSED_ERROR_CODE


def whatsapp_config() -> dict[str, str]:
    return get_instance_settings(
        [
            "WHATSAPP_APP_ACCESS_TOKEN",
            "WHATSAPP_APP_APP_SECRET",
            "WHATSAPP_APP_VERIFY_TOKEN",
            "WHATSAPP_APP_PHONE_NUMBER_ID",
        ]
    )


class WhatsAppBotClient:
    def __init__(self, *, access_token: str | None = None, phone_number_id: str | None = None) -> None:
        if access_token is None or phone_number_id is None:
            config = whatsapp_config()
            access_token = access_token or str(config["WHATSAPP_APP_ACCESS_TOKEN"] or "")
            phone_number_id = phone_number_id or str(config["WHATSAPP_APP_PHONE_NUMBER_ID"] or "")
        self._access_token = access_token
        self._phone_number_id = phone_number_id
        if not self._access_token or not self._phone_number_id:
            raise WhatsAppApiError("WhatsApp access token or phone number id is not configured")

    def _call(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{GRAPH_API_BASE_URL}/{path}"
        try:
            response = requests.request(
                method,
                url,
                json=payload,
                headers={"Authorization": f"Bearer {self._access_token}"},
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            # Keep only the exception class name — the message may embed request details.
            raise WhatsAppApiError(f"WhatsApp API request failed: {type(exc).__name__} for {path}") from None
        try:
            data = response.json()
        except ValueError:
            raise WhatsAppApiError(f"WhatsApp API returned non-JSON (HTTP {response.status_code}) for {path}")
        if not response.ok:
            error = data.get("error") or {}
            code = error.get("code")
            raise WhatsAppApiError(
                f"WhatsApp API error for {path}: HTTP {response.status_code}, "
                f"code {code}, {error.get('message', 'unknown')}",
                code=code if isinstance(code, int) else None,
            )
        return data if isinstance(data, dict) else {"result": data}

    def send_message(self, *, to: str, text: str, reply_to_message_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            # Plain text on purpose: WhatsApp renders its own lightweight markup, and
            # an escaping layer would add a failure mode without adding meaning.
            "text": {"preview_url": False, "body": text},
        }
        if reply_to_message_id:
            payload["context"] = {"message_id": reply_to_message_id}
        return self._call("POST", f"{self._phone_number_id}/messages", payload)

    def send_reaction(self, *, to: str, message_id: str, emoji: str) -> None:
        self._call(
            "POST",
            f"{self._phone_number_id}/messages",
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "reaction",
                "reaction": {"message_id": message_id, "emoji": emoji},
            },
        )

    def get_phone_number(self) -> dict[str, Any]:
        return self._call("GET", f"{self._phone_number_id}?fields=display_phone_number")

    def subscribe_app(self, *, waba_id: str) -> dict[str, Any]:
        """Subscribe the Meta app to the WhatsApp Business Account's webhook events.

        The webhook URL and verify token themselves are configured in the Meta App
        Dashboard; this is the remaining API-side step that actually turns event
        delivery on for the WABA.
        """
        return self._call("POST", f"{waba_id}/subscribed_apps")


def get_bot_phone_number() -> str:
    """The bot number's digits (for ``wa.me`` deep links), cached per process cluster.

    Graph API returns a display-formatted number ("+1 555-025-3483"); ``wa.me`` links
    want bare digits with the country code.
    """
    cached = cache.get(_BOT_PHONE_CACHE_KEY)
    if isinstance(cached, str) and cached:
        return cached
    display = str(WhatsAppBotClient().get_phone_number().get("display_phone_number") or "")
    digits = re.sub(r"\D", "", display)
    if not digits:
        raise WhatsAppApiError("WhatsApp phone number lookup returned no number")
    cache.set(_BOT_PHONE_CACHE_KEY, digits, timeout=int(_BOT_PHONE_CACHE_TTL.total_seconds()))
    return digits
