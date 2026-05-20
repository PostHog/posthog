"""
Celery tasks for legal_documents.

Async entrypoints that call the facade (facade/api.py).
Keep task functions thin - only call facade methods.
"""

from __future__ import annotations

import structlog
from celery import shared_task

from posthog.exceptions_capture import capture_exception
from posthog.scoping_audit import skip_team_scope_audit

from products.legal_documents.backend.logic import (
    pandadoc as pandadoc_client,
    send_pandadoc_envelope_now,
)
from products.legal_documents.backend.models import LegalDocument

logger = structlog.get_logger(__name__)


# Celery retry budget for transient PandaDoc /send failures that survive the
# in-process urllib3 retry budget. Stretches the recovery window from seconds
# (the HTTP adapter) to ~tens of minutes — long enough to ride out a PandaDoc
# outage but bounded so a permanently broken envelope eventually surfaces.
@shared_task(
    ignore_result=True,
    autoretry_for=(pandadoc_client.PandaDocError,),
    retry_backoff=60,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
)
@skip_team_scope_audit  # LegalDocument is org-scoped, not team-scoped.
def retry_send_pandadoc_envelope(document_id: str) -> None:
    """
    Re-dispatch the signing email for a previously-created PandaDoc envelope
    after a transient send failure. Celery retries this task with exponential
    backoff if PandaDoc is still unreachable; the task is a no-op once the
    envelope is either dispatched or the row has flipped to signed.
    """
    try:
        document = LegalDocument.objects.get(id=document_id)
    except LegalDocument.DoesNotExist:
        logger.warning("legal_document_pandadoc_send_retry_missing_row", document_id=document_id)
        return
    if document.status == LegalDocument.Status.SIGNED:
        return
    if not document.pandadoc_document_id:
        logger.warning(
            "legal_document_pandadoc_send_retry_missing_envelope_id",
            document_id=document_id,
        )
        return
    try:
        send_pandadoc_envelope_now(document)
    except pandadoc_client.PandaDocError as exc:
        logger.warning(
            "legal_document_pandadoc_send_retry_failed",
            document_id=document_id,
            pandadoc_document_id=document.pandadoc_document_id,
            error=str(exc),
        )
        capture_exception(
            exc,
            additional_properties={
                "legal_document_id": document_id,
                "pandadoc_document_id": document.pandadoc_document_id,
            },
        )
        raise
