"""Inbound PandaDoc deliveries for the signing flow.

Reached from the facade after ingress verified the HMAC over the raw body and split a batched
body into one delivery per event. No HTTP in here: ingress owns the request and the receipt, so
a state PandaDoc sends that means nothing here is a log line rather than a status code.
"""

from __future__ import annotations

from typing import Any

import structlog

from posthog.ingress.contracts import WebhookDelivery

from .. import logic
from ..models import LegalDocument

logger = structlog.get_logger(__name__)


def _mark_envelope_ready(*, pandadoc_document_id: str, template_id: str) -> LegalDocument | None:
    """The envelope finished template processing and is ready to send, so dispatch the signing email.

    Idempotent: if the envelope has already been dispatched (row is already signed, or the send
    call fails because PandaDoc has moved past draft) we quietly skip.
    """
    document = logic.get_by_pandadoc_document_id(pandadoc_document_id)
    if document is None:
        return None
    if not logic.template_id_matches_document(document, template_id):
        return None
    if document.status == LegalDocument.Status.SIGNED:
        # The envelope already completed, so this draft event is a late or replayed delivery
        # with nothing left to do.
        return document
    logic.send_pandadoc_envelope(document)
    return document


def _mark_signed(*, pandadoc_document_id: str, template_id: str) -> LegalDocument | None:
    """Record the signature for a completed envelope.

    - Looks up the row by the PandaDoc document uuid (no IDOR surface: unknown ids are a no-op).
    - Double-checks the template matches the stored document variant, to guard against
      misconfigured PandaDoc templates flipping the wrong row.
    - Claims the row with a conditional flip to signed, then fires analytics and BAA side
      effects and schedules the signed-PDF archive as a retried background job.

    The signature is recorded as soon as the delivery lands. It is never gated on the PDF
    archival, which used to leave the row stuck when a download or upload failed. Idempotent:
    a delivery that does not win the claim returns the row without re-firing side effects.
    """
    document = logic.get_by_pandadoc_document_id(pandadoc_document_id)
    if document is None:
        return None
    if not logic.template_id_matches_document(document, template_id):
        return None
    # PandaDoc sends no delivery id, so ingress cannot dedup. Two `document.completed` deliveries
    # can both read the row as pending, and only this conditional update decides which one owns
    # the side effects.
    if not logic.try_mark_signed_if_pending(document):
        current = logic.get_by_pandadoc_document_id(pandadoc_document_id)
        if current is None:
            return None
        if current.status == LegalDocument.Status.SIGNED:
            logger.info("pandadoc_webhook_already_signed", pandadoc_document_id=pandadoc_document_id)
        else:
            logger.warning(
                "pandadoc_webhook_completed_for_unexpected_status",
                pandadoc_document_id=pandadoc_document_id,
                status=current.status,
            )
        return current
    # The side effects read the status off the instance the update never touched.
    document.status = LegalDocument.Status.SIGNED
    logic.apply_baa_signed_side_effects(document)
    logic.fire_legal_document_signed_event(document)
    logic.schedule_pdf_archive(document)
    return document


def accept_pandadoc_event(delivery: WebhookDelivery) -> None:
    """Apply one verified PandaDoc delivery to the document it names."""
    data: Any = delivery.payload.get("data") or {}
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        return

    event_status = data.get("status")
    pandadoc_document_id = data.get("id") or ""
    template_id = (data.get("template") or {}).get("id") if isinstance(data.get("template"), dict) else ""

    if not pandadoc_document_id:
        logger.warning("pandadoc_webhook_event_missing_id", status=event_status)
        return

    if event_status == logic.PANDADOC_DRAFT_STATUS:
        document = _mark_envelope_ready(pandadoc_document_id=pandadoc_document_id, template_id=template_id or "")
    elif event_status == logic.PANDADOC_COMPLETED_STATUS:
        document = _mark_signed(pandadoc_document_id=pandadoc_document_id, template_id=template_id or "")
    else:
        logger.info("pandadoc_webhook_state_ignored", status=event_status, pandadoc_document_id=pandadoc_document_id)
        return

    if document is None:
        logger.info("pandadoc_webhook_no_matching_document", pandadoc_document_id=pandadoc_document_id)
