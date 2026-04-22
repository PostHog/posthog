"""
Thin client for the PandaDoc public API.

We only hit two endpoints:
    POST /public/v1/documents         -> create a document from a template
    POST /public/v1/documents/{id}/send -> email the signing envelope

Plus one helper for verifying the HMAC signature on inbound webhooks. Keeping
this file free of Django/DRF imports so it's straightforward to unit test.
"""

from __future__ import annotations

import hmac
import hashlib
from dataclasses import dataclass
from typing import Any

from django.conf import settings

import requests
import structlog

logger = structlog.get_logger(__name__)


DEFAULT_TIMEOUT_SECONDS = 30


class PandaDocError(Exception):
    """Raised when the PandaDoc API returns a non-2xx response or we fail to reach it."""


class PandaDocNotConfigured(PandaDocError):
    """Raised when we try to use the client but the API key is missing."""


@dataclass(frozen=True)
class PandaDocDocument:
    id: str
    status: str
    name: str


@dataclass(frozen=True)
class PandaDocSenderPostHog:
    """
    We wanna make sure we always have someone from our team attached as a CC
    on the PandaDoc envelopes, so let's assign it here.
    """

    email: str = "sales@posthog.com"
    role: str = "PostHog"


@dataclass(frozen=True)
class PandaDocRecipient:
    email: str
    # Built-in recipient contact fields. PandaDoc auto-populates `Client.Email`,
    # `Client.Company`, and `Client.StreetAddress` in the template body from
    # these values, so no custom tokens are needed.
    company: str = ""
    street_address: str = ""
    role: str = "Client"


class PandaDocClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._api_key = api_key if api_key is not None else settings.PANDADOC_API_KEY
        self._base_url = (base_url if base_url is not None else settings.PANDADOC_API_BASE_URL).rstrip("/")
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        if not self._api_key:
            raise PandaDocNotConfigured("PANDADOC_API_KEY is not configured.")
        return {
            "Authorization": f"API-Key {self._api_key}",
            "Content-Type": "application/json",
        }

    def _post(self, path: str, json: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            response = requests.post(url, headers=self._headers(), json=json, timeout=self._timeout)
        except requests.RequestException as exc:
            raise PandaDocError(f"Network error calling PandaDoc {path}: {exc}") from exc
        if response.status_code >= 400:
            raise PandaDocError(f"PandaDoc {path} returned {response.status_code}: {response.text[:500]}")
        # Some endpoints (like /send) return empty bodies — treat that as an empty dict.
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise PandaDocError(f"PandaDoc {path} returned non-JSON body: {exc}") from exc

    def create_document_from_template(
        self,
        *,
        template_id: str,
        name: str,
        recipients: list[PandaDocRecipient | PandaDocSenderPostHog],
        metadata: dict[str, str] | None = None,
    ) -> PandaDocDocument:
        """
        Create a new document from a PandaDoc template. The returned document is in
        `document.uploaded` state — call `send_document` to dispatch the signing email.
        """
        payload: dict[str, Any] = {
            "name": name,
            "template_uuid": template_id,
            "recipients": [_serialize_recipient(r) for r in recipients],
        }
        if metadata:
            payload["metadata"] = metadata
        data = self._post("/public/v1/documents", payload)
        return PandaDocDocument(
            id=data["id"],
            status=data.get("status", ""),
            name=data.get("name", name),
        )

    def send_document(self, *, document_id: str, subject: str, message: str) -> None:
        """
        Trigger the signing envelope email. PandaDoc returns 200/202 with a body we don't use.
        """
        self._post(
            f"/public/v1/documents/{document_id}/send",
            {"subject": subject, "message": message, "silent": False},
        )


def _serialize_recipient(r: PandaDocRecipient | PandaDocSenderPostHog) -> dict[str, Any]:
    payload: dict[str, Any] = {"email": r.email, "role": r.role}
    # PandaDoc expects contact fields under `fields`, keyed by the snake_case
    # field name (e.g. `Client.Company` → `company`). Only include fields we
    # actually have a value for so we don't stomp existing template defaults,
    # and only for recipient types that declare them (the PostHog sender doesn't).
    fields: dict[str, dict[str, str]] = {}
    if company := getattr(r, "company", ""):
        fields["company"] = {"value": company}
    if street_address := getattr(r, "street_address", ""):
        fields["street_address"] = {"value": street_address}

    if fields:
        payload["fields"] = fields
    return payload


def verify_webhook_signature(*, secret: str, body: bytes, signature: str) -> bool:
    """
    PandaDoc signs webhooks with HMAC-SHA256 of the raw body using the shared secret
    configured in the PandaDoc dashboard. They expose the hex digest as a query parameter
    (`?signature=...`) and as the `X-PandaDoc-Signature` header on modern deliveries.

    Both the header and query-param forms are accepted — we just compare constants.
    """
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
