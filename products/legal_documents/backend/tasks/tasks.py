"""
Celery tasks for legal_documents.

Async entrypoints that call the facade (facade/api.py).
Keep task functions thin — only call facade methods.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from celery import shared_task

from ..facade import api

logger = structlog.get_logger(__name__)


# Task names are pinned so the registered identity is independent of the import
# path — core re-exports these through facade/tasks.py to call `.s()`.
@shared_task(
    name="products.legal_documents.backend.tasks.archive_signed_legal_document_pdf",
    ignore_result=True,
    autoretry_for=(api.LegalDocumentPdfArchiveFailed,),
    retry_backoff=30,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=8,
)
def archive_signed_legal_document_pdf(document_id: str) -> None:
    api.archive_signed_pdf(UUID(document_id))


@shared_task(
    name="products.legal_documents.backend.tasks.reconcile_pending_legal_documents",
    ignore_result=True,
    # Runs every 15 minutes; limits stay well under that so a slow run can't overlap the next tick.
    soft_time_limit=180,
    time_limit=300,
)
def reconcile_pending_legal_documents() -> None:
    result = api.reconcile_pending_signatures()
    logger.info(
        "legal_documents.reconcile_swept",
        newly_signed=result.newly_signed,
        archives_requeued=result.archives_requeued,
        errors=result.errors,
    )
