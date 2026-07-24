"""
Thin client for the PandaDoc public API.

We hit these endpoints:
    POST  /public/v1/documents              -> create a document from a template
    GET   /public/v1/documents/{id}         -> read an envelope's current status
    POST  /public/v1/documents/{id}/send    -> email the signing envelope
    PATCH /public/v1/documents/{id}/status  -> move an envelope to voided (no longer signable)

Plus one helper for verifying the HMAC signature on inbound webhooks. Keeping
this file free of Django/DRF imports so it's straightforward to unit test.
"""

from __future__ import annotations

import hmac
import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import IO, Any

from django.conf import settings

import requests
import structlog

logger = structlog.get_logger(__name__)


DEFAULT_TIMEOUT_SECONDS = 30

# PandaDoc encodes document statuses as small integers in the status-change API.
# 11 is `document.voided` — the document is no longer available for signature
# but stays in PandaDoc as an audit record of the cancelled signing process.
# See https://developers.pandadoc.com/reference/change-document-status-manually
_PANDADOC_STATUS_VOIDED = 11

# The only PandaDoc states from which a void (→ `document.voided`) is both
# necessary and permitted: the envelope has actually been emailed to the signer
# and carries a live signing link a recipient could still complete. Every other
# state — never dispatched (`document.uploaded`/`document.draft`/`document.error`
# /`document.scheduled`), still in an internal approval/review/payment workflow,
# or already terminal (`document.completed`/`voided`/`declined`) — has no live
# link to invalidate, and PandaDoc rejects a void from those states anyway. We
# treat all of them as a no-op so a stranded row can always be cleaned up.
# https://developers.pandadoc.com/reference/document-status
_PANDADOC_VOIDABLE_STATUSES = frozenset({"document.sent", "document.viewed"})


class PandaDocError(Exception):
    """Raised when the PandaDoc API returns a non-2xx response or we fail to reach it."""


class PandaDocNotConfigured(PandaDocError):
    """Raised when we try to use the client but the API key is missing."""


@dataclass(frozen=True)
class PandaDocDocument:
    id: str
    status: str
    name: str


class PandaDocRole(StrEnum):
    """
    Roles PandaDoc templates bind recipients to. Must match the role names
    configured on each template in the PandaDoc dashboard.
    """

    CLIENT = "Client"
    POSTHOG = "PostHog"


@dataclass(frozen=True)
class PandaDocRecipient:
    email: str
    role: PandaDocRole


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

    def _get(self, path: str, *, allow_missing: bool = False) -> dict[str, Any] | None:
        """
        GET the given path and return the decoded JSON body. When
        `allow_missing` is set, a 404 returns None instead of raising — the
        caller treats an already-gone document as a no-op.
        """
        url = f"{self._base_url}{path}"
        try:
            response = requests.get(url, headers=self._headers(), timeout=self._timeout)
        except requests.RequestException as exc:
            raise PandaDocError(f"Network error calling PandaDoc {path}: {exc}") from exc
        if allow_missing and response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise PandaDocError(f"PandaDoc {path} returned {response.status_code}: {response.text[:500]}")
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise PandaDocError(f"PandaDoc {path} returned non-JSON body: {exc}") from exc

    def _patch(self, path: str, json: dict[str, Any]) -> int:
        """
        PATCH the given path with a JSON body. Returns the HTTP status code so
        callers can distinguish a successful change (204) from a "no-op,
        already gone" (404) without inspecting an exception.
        """
        url = f"{self._base_url}{path}"
        try:
            response = requests.patch(url, headers=self._headers(), json=json, timeout=self._timeout)
        except requests.RequestException as exc:
            raise PandaDocError(f"Network error calling PandaDoc {path}: {exc}") from exc
        if response.status_code == 404:
            return response.status_code
        if response.status_code >= 400:
            raise PandaDocError(f"PandaDoc {path} returned {response.status_code}: {response.text[:500]}")
        return response.status_code

    @contextmanager
    def _get_stream(self, path: str) -> Iterator[IO[bytes]]:
        """
        Open a streaming GET to PandaDoc and yield the raw binary stream.
        Keeps peak memory flat regardless of payload size — the caller pipes
        bytes straight from the socket to wherever they're going (e.g. S3).
        """
        url = f"{self._base_url}{path}"
        try:
            with requests.get(url, headers=self._headers(), stream=True, timeout=self._timeout) as response:
                if response.status_code >= 400:
                    raise PandaDocError(f"PandaDoc {path} returned {response.status_code}: {response.text[:500]}")
                # Transparently handle gzip/deflate on the wire so consumers
                # see the decoded body.
                response.raw.decode_content = True
                yield response.raw
        except requests.RequestException as exc:
            raise PandaDocError(f"Network error calling PandaDoc {path}: {exc}") from exc

    def create_document_from_template(
        self,
        *,
        template_id: str,
        name: str,
        recipients: list[PandaDocRecipient],
        owner_email: str | None = None,
        tokens: dict[str, str] | None = None,
        metadata: dict[str, str] | None = None,
    ) -> PandaDocDocument:
        """
        Create a new document from a PandaDoc template. The returned document is in
        `document.uploaded` state — call `send_document` to dispatch the signing email.

        `owner_email` sets the PandaDoc user who owns the document inside the workspace.
        It does *not* affect the "From" identity in signing emails — that's controlled
        by `sender_email` on `send_document`.

        `tokens` is a flat {name: value} map that maps onto the template's token
        placeholders (`[Client.Company]`, `[Client.StreetAddress]`, etc.). Only
        `Client.Email` is auto-populated from the recipient — everything else
        the template references has to be passed explicitly here.
        """
        payload: dict[str, Any] = {
            "name": name,
            "template_uuid": template_id,
            "recipients": [_serialize_recipient(r) for r in recipients],
        }

        if owner_email:
            payload["owner"] = {"email": owner_email}
        if tokens:
            payload["tokens"] = [{"name": name, "value": value} for name, value in tokens.items()]
        if metadata:
            payload["metadata"] = metadata

        data = self._post("/public/v1/documents", payload)
        return PandaDocDocument(
            id=data["id"],
            status=data.get("status", ""),
            name=data.get("name", name),
        )

    def send_document(
        self,
        *,
        document_id: str,
        subject: str,
        message: str,
        sender_email: str | None = None,
    ) -> None:
        """
        Trigger the signing envelope email. PandaDoc returns 200/202 with a body we don't use.

        `sender_email` controls the "From" identity recipients see in the signing
        email. Without it, PandaDoc falls back to the owner of the API key — the
        `sender` set during document creation does not affect the send-time email.
        """
        payload: dict[str, Any] = {"subject": subject, "message": message, "silent": False}
        if sender_email:
            payload["sender"] = {"email": sender_email}
        self._post(f"/public/v1/documents/{document_id}/send", payload)

    def get_document_status(self, *, document_id: str) -> str | None:
        """
        Return the envelope's current PandaDoc status string (e.g.
        `document.sent`), or None if the document no longer exists on
        PandaDoc's side. Backed by the lightweight status endpoint.
        """
        data = self._get(f"/public/v1/documents/{document_id}", allow_missing=True)
        if data is None:
            return None
        return data.get("status", "")

    def void_document(self, *, document_id: str, notify_recipients: bool = True) -> None:
        """
        Move a *sent* envelope to `document.voided` so the recipient can no
        longer complete it. Unlike a hard delete, the envelope stays in
        PandaDoc as an audit record of the cancelled signing process — which
        is what we want for documents that may end up in a legal review later.

        `notify_recipients=True` sends PandaDoc's standard "this document was
        cancelled" email to the original signer, so they're not left
        wondering why the link from earlier no longer works.

        Only envelopes that were actually emailed to a signer
        (`document.sent`/`document.viewed`) are voided. An envelope that never
        left PandaDoc (still processing the template, or ready but never sent
        because the `document.draft` webhook was missed) has no live signing
        link, and PandaDoc rejects a void from those states anyway — so we skip
        it as a no-op rather than hard-failing. That keeps a stranded row
        deletable (and therefore regenerable) instead of wedging it. A
        document that's already gone (404) is a no-op for the same reason.

        A void that *is* attempted but fails (e.g., 423 if PandaDoc has the
        document locked for editing) surfaces as PandaDocError so the caller
        can decide whether to retry or log + move on.
        """
        if self.get_document_status(document_id=document_id) not in _PANDADOC_VOIDABLE_STATUSES:
            return
        self._patch(
            f"/public/v1/documents/{document_id}/status",
            {"status": _PANDADOC_STATUS_VOIDED, "notify_recipients": notify_recipients},
        )

    @contextmanager
    def stream_document(self, *, document_id: str) -> Iterator[IO[bytes]]:
        """
        Open a streaming download for a completed document's signed PDF.
        PandaDoc's `document.completed` webhook doesn't carry a signed-PDF URL,
        so this is how we actually retrieve the artifact. Use as a context
        manager — the underlying HTTP connection is released on exit.
        """
        with self._get_stream(f"/public/v1/documents/{document_id}/download") as stream:
            yield stream


def _serialize_recipient(r: PandaDocRecipient) -> dict[str, Any]:
    return {"email": r.email, "role": str(r.role)}


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
