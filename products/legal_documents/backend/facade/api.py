"""
Facade for legal_documents.

This is the ONLY module other products (and the presentation layer) are allowed
to import. Accepts frozen dataclasses as input, returns frozen dataclasses as
output, and never leaks ORM instances or QuerySets across the boundary.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from django.db import transaction

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.organization import Organization
from posthog.ph_client import ph_scoped_capture

from .. import logic
from ..logic.pandadoc import (
    PandaDocError,
    verify_webhook_signature as _verify_pandadoc_webhook_signature,
)
from ..models import LegalDocument
from . import contracts
from .enums import LegalDocumentStatus

logger = structlog.get_logger(__name__)


class LegalDocumentPdfArchiveFailed(Exception):
    """
    Raised by the background archive task when it can't pull the signed PDF from
    PandaDoc or write it to object storage. The row is already `signed` — only
    the download copy is missing — so the task retries and the reconciliation
    sweep re-enqueues it if every retry is exhausted.
    """


def _to_dto(doc: LegalDocument) -> contracts.LegalDocumentDTO:
    creator = doc.created_by
    return contracts.LegalDocumentDTO(
        id=doc.id,
        document_type=doc.document_type,
        company_name=doc.company_name,
        representative_email=doc.representative_email,
        status=doc.status,
        signed_pdf_stored=doc.signed_pdf_stored,
        created_by=(
            contracts.LegalDocumentCreator(first_name=creator.first_name or "", email=creator.email)
            if creator is not None
            else None
        ),
        created_at=doc.created_at,
    )


def list_for_organization(organization_id: UUID) -> list[contracts.LegalDocumentDTO]:
    return [_to_dto(doc) for doc in logic.list_for_organization(organization_id)]


def get_for_organization(document_id: UUID, organization_id: UUID) -> contracts.LegalDocumentDTO | None:
    document = logic.get_for_organization(document_id, organization_id)
    return _to_dto(document) if document is not None else None


def get_signed_pdf_download_url(document_id: UUID, organization_id: UUID) -> str | None:
    """
    Return a short-lived presigned URL for the signed PDF, or None if the
    document doesn't exist, isn't signed yet, or the PDF isn't in object
    storage (upload failed, storage disabled).
    """
    document = logic.get_for_organization(document_id, organization_id)
    if document is None or document.status != LegalDocumentStatus.SIGNED or not document.signed_pdf_stored:
        return None
    return logic.get_signed_pdf_presigned_url(document)


def has_qualifying_baa_addon(organization: Organization) -> bool:
    return logic.has_qualifying_baa_addon(organization)


def verify_pandadoc_webhook_signature(*, secret: str, body: bytes, signature: str) -> bool:
    """Passthrough so the presentation layer never reaches past the facade."""
    return _verify_pandadoc_webhook_signature(secret=secret, body=body, signature=signature)


def exists_for_organization_and_type(organization_id: UUID, document_type: str) -> bool:
    return logic.exists_for_organization_and_type(organization_id, document_type)


class LegalDocumentNotFound(Exception):
    """Raised when a delete targets a row that doesn't exist (or belongs to a different org)."""


class LegalDocumentAlreadySigned(Exception):
    """Raised when a delete targets a row in `signed` state, which is admin-only."""


class LegalDocumentVoidFailed(Exception):
    """
    Raised when the PandaDoc envelope void during a self-serve delete fails.
    The row was not deleted (the surrounding transaction rolled back). The
    caller should surface a retriable error to the user so they don't end up
    in the broken state where the row is gone but the envelope is still
    signable.
    """


def delete_document(document_id: UUID, organization_id: UUID) -> None:
    """
    Self-serve deletion entry point for org admins.

    Wrapped in a transaction with `select_for_update` so we can't race a
    concurrent `document.completed` webhook flipping status to signed
    between the gate check and the delete. The lock is held for the
    duration of the PandaDoc void (normally subsecond, up to a 30s timeout
    in the worst case). Webhooks landing concurrently either lose the race
    and see the row gone (404 → no-op in the webhook handler) or win and
    flip status before our `select_for_update` resolves; in that second
    case our re-check raises LegalDocumentAlreadySigned and rolls back.

    PandaDoc void runs in strict mode here: a PandaDoc error rolls back the
    whole transaction (row stays, frontend retries). Better than telling
    the user the envelope was cancelled when it wasn't and leaving the
    original signer with a still-completable document.

    Refuses signed documents — those are completed legal artifacts and stay
    admin-only (Django admin bypasses this guard by calling
    `logic.delete_document` directly with `strict_pandadoc=False`).

    Raises:
        LegalDocumentNotFound: row doesn't exist or belongs to a different org.
        LegalDocumentAlreadySigned: row is signed at lock time.
        LegalDocumentVoidFailed: PandaDoc void failed; row was not deleted.
    """
    try:
        with transaction.atomic():
            try:
                document = LegalDocument.objects.select_for_update().get(
                    id=document_id, organization_id=organization_id
                )
            except LegalDocument.DoesNotExist:
                raise LegalDocumentNotFound(
                    f"Legal document {document_id} not found for organization {organization_id}"
                )
            if document.status == LegalDocumentStatus.SIGNED:
                raise LegalDocumentAlreadySigned(
                    f"Legal document {document_id} is already signed and can't be deleted from the self-serve UI"
                )
            # The PandaDoc void runs inside the row lock on purpose: if it
            # ran after commit, a void failure would leave the row deleted
            # but the envelope still signable. Holding the lock through a
            # (rare, slow-path) HTTP call is the deliberate trade for
            # making the row delete and the void atomic from the user's
            # perspective.
            logic.delete_document(document, strict_pandadoc=True)
    except PandaDocError as exc:
        raise LegalDocumentVoidFailed(
            f"Failed to cancel the PandaDoc envelope for legal document {document_id}: {exc}"
        ) from exc


def create_document(data: contracts.CreateLegalDocumentInput) -> contracts.LegalDocumentDTO:
    document = logic.create_document(
        organization_id=data.organization_id,
        created_by_id=data.created_by_id,
        document_type=data.document_type,
        company_name=data.company_name,
        company_address=data.company_address,
        representative_email=data.representative_email,
    )

    # Fire and forget: PandaDoc never blocks the response. The envelope lands
    # in `document.uploaded` state and becomes dispatchable asynchronously —
    # the `document.draft` webhook triggers the actual send via
    # `mark_envelope_ready_by_pandadoc_document_id`.
    logic.create_pandadoc_envelope(document)
    logic.fire_legal_document_submitted_event(document, distinct_id=data.distinct_id)

    return _to_dto(document)


def mark_envelope_ready_by_pandadoc_document_id(
    *,
    pandadoc_document_id: str,
    template_id: str,
) -> contracts.LegalDocumentDTO | None:
    """
    Entry point from the PandaDoc `document.draft` webhook — the envelope
    finished template processing and is ready to send. Dispatch the signing
    email.

    Idempotent: if the envelope has already been dispatched (row is already
    signed, or the send call fails because PandaDoc has moved past draft)
    we quietly skip.
    """
    document = logic.get_by_pandadoc_document_id(pandadoc_document_id)
    if document is None:
        return None
    if not logic.template_id_matches_document(document, template_id):
        return None
    if document.status == LegalDocumentStatus.SIGNED:
        # Envelope already completed — the draft event is a late/replayed
        # delivery; nothing left for us to do.
        return _to_dto(document)
    logic.send_pandadoc_envelope(document)
    return _to_dto(document)


def mark_signed_by_pandadoc_document_id(
    *,
    pandadoc_document_id: str,
    template_id: str,
) -> contracts.LegalDocumentDTO | None:
    """
    Entry point from the PandaDoc `document.completed` webhook. The caller must
    have already verified the HMAC signature on the raw body; this function:

    - Looks up the row by the PandaDoc document uuid (no IDOR surface: unknown ids 404).
    - Double-checks the template matches the stored document variant, to guard
      against misconfigured PandaDoc templates flipping the wrong row.
    - Flips status to signed, fires analytics and BAA side effects, and schedules
      the signed-PDF archive as a retried background job.

    The signature is recorded as soon as the webhook lands — it is never gated
    on the PDF archival, which used to leave the row stuck when a download or
    upload failed. Idempotent: an already-signed row returns its DTO without
    re-firing side effects.
    """
    document = logic.get_by_pandadoc_document_id(pandadoc_document_id)
    if document is None:
        return None
    if not logic.template_id_matches_document(document, template_id):
        return None
    if document.status == LegalDocumentStatus.SIGNED:
        return _to_dto(document)
    return _to_dto(_mark_signed_and_schedule_archive(document))


def _mark_signed_and_schedule_archive(document: LegalDocument) -> LegalDocument:
    document = logic.mark_document_signed(document)
    logic.apply_baa_signed_side_effects(document)
    logic.fire_legal_document_signed_event(document)
    _schedule_pdf_archive(document)
    return document


def _try_mark_signed_and_schedule_archive(
    document: LegalDocument, capture: Callable[..., None] | None = None, delay_seconds: int = 0
) -> bool:
    """
    Reconcile-only variant of `_mark_signed_and_schedule_archive`. The sweep's
    queryset snapshot can be stale by the time this runs, so it uses the
    conditional-update helper instead of an unconditional save. A document a
    concurrent webhook already signed loses the race and its side effects are
    skipped rather than re-fired.
    """
    if not logic.try_mark_signed_if_pending(document):
        return False
    logic.apply_baa_signed_side_effects(document)
    logic.fire_legal_document_signed_event(document, capture=capture)
    _schedule_pdf_archive(document, delay_seconds=delay_seconds)
    return True


def _schedule_pdf_archive(document: LegalDocument, delay_seconds: int = 0) -> None:
    # Local import breaks the facade ⇄ tasks import cycle (tasks import the facade).
    from ..tasks.tasks import archive_signed_legal_document_pdf  # noqa: PLC0415

    document_id = str(document.id)
    transaction.on_commit(
        lambda: archive_signed_legal_document_pdf.apply_async(args=[document_id], countdown=delay_seconds)
    )


def archive_signed_pdf(document_id: UUID) -> None:
    """
    Pull the signed PDF from PandaDoc and write it to object storage, then mark
    the row archived. Called from the background task. Raises
    LegalDocumentPdfArchiveFailed on any download/upload failure so the task
    retries; a no-op if the row is gone or already archived.
    """
    document = logic.get_by_id(document_id)
    if document is None or document.signed_pdf_stored:
        return
    if not logic.download_and_store_signed_pdf(document):
        raise LegalDocumentPdfArchiveFailed(f"Failed to archive signed PDF for legal_document {document_id}")
    logic.mark_signed_pdf_stored(document)


def reconcile_pending_signatures() -> contracts.LegalDocumentReconcileResult:
    """
    Safety net for the whole completion path. Polls PandaDoc for every row we
    still think is out for signature and marks the completed ones — recovering
    dropped, throttled, or 204'd `document.completed` webhooks and clearing the
    backlog. Also re-enqueues the archive for signed rows whose PDF never landed.

    Each row is processed independently: `list_pending_signature_documents` is
    ordered oldest-first, so one row that deterministically errors (a bad
    PandaDoc response, a DB hiccup) must not block every row behind it on every
    15-minute tick.
    """
    newly_signed = 0
    errors = 0
    pending_seen = 0
    # PandaDoc allows 100 downloads a minute across the whole account, shared with
    # live signings. Staggering one archive per second keeps a backlog drain from
    # starving a customer signing right now, and holds regardless of worker count.
    scheduled_archives = 0
    signed_this_run: set[UUID] = set()
    # One scoped client for the whole loop, not one per row: this runs in a Celery
    # worker, where the global client's background flush may never run before the
    # process exits, and the scoped client blocks for seconds on setup and flush.
    # Losing these events would hide whether the sweep is recovering anything.
    with ph_scoped_capture() as capture:
        for document in logic.list_pending_signature_documents():
            pending_seen += 1
            try:
                if logic.get_pandadoc_document_status(document) == logic.PANDADOC_COMPLETED_STATUS:
                    if _try_mark_signed_and_schedule_archive(
                        document, capture=capture, delay_seconds=scheduled_archives
                    ):
                        newly_signed += 1
                        scheduled_archives += 1
                        signed_this_run.add(document.id)
            except Exception as exc:
                errors += 1
                logger.exception("legal_document_reconcile_pending_row_failed", document_id=str(document.id))
                capture_exception(exc, additional_properties={"legal_document_id": str(document.id)})

    # The pending query is oldest-first and capped per run. When it fills the cap,
    # newer rows fall off this run's tail and wait for a later tick — surface the
    # binding cap instead of truncating silently, so a real backlog is visible.
    if pending_seen >= logic.RECONCILE_MAX_PER_RUN:
        logger.warning(
            "legal_document_reconcile_pending_cap_reached",
            processed=pending_seen,
            cap=logic.RECONCILE_MAX_PER_RUN,
        )

    # Rows this run just signed and already scheduled an archive for above.
    # excluding them here is what keeps the archive from being `.delay()`'d twice.
    archives_requeued = 0
    for document in logic.list_signed_documents_missing_pdf(exclude_ids=signed_this_run):
        try:
            _schedule_pdf_archive(document, delay_seconds=scheduled_archives)
            archives_requeued += 1
            scheduled_archives += 1
        except Exception as exc:
            errors += 1
            logger.exception("legal_document_reconcile_archive_row_failed", document_id=str(document.id))
            capture_exception(exc, additional_properties={"legal_document_id": str(document.id)})

    return contracts.LegalDocumentReconcileResult(
        newly_signed=newly_signed,
        archives_requeued=archives_requeued,
        errors=errors,
    )
