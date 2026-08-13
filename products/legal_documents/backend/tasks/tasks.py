"""
Celery tasks for legal_documents.

Async entrypoints that call the facade (facade/api.py).
Keep task functions thin — only call facade methods.
"""

from __future__ import annotations

from uuid import UUID

from celery import shared_task

from ..facade import api


@shared_task(
    ignore_result=True,
    autoretry_for=(api.LegalDocumentPdfArchiveFailed,),
    retry_backoff=30,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=8,
)
def archive_signed_legal_document_pdf(document_id: str) -> None:
    api.archive_signed_pdf(UUID(document_id))


@shared_task(ignore_result=True)
def reconcile_pending_legal_documents() -> None:
    api.reconcile_pending_signatures()
