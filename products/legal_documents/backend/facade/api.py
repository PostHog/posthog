"""
Facade for legal_documents.

This is the ONLY module other products (and the presentation layer) are allowed
to import. Accepts frozen dataclasses as input, returns frozen dataclasses as
output, and never leaks ORM instances or QuerySets across the boundary.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import IO
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.ingress.contracts import WebhookDelivery
from posthog.models.organization import Organization
from posthog.ph_client import ph_scoped_capture

from .. import logic
from ..logic import (
    SIGNED_BAA_ANNOTATION as SIGNED_BAA_ANNOTATION,
    webhooks,
)
from ..logic.pandadoc import PandaDocError
from ..models import LegalDocument
from . import contracts
from .enums import (
    BaaBlockReason,
    DocumentType,
    LegalDocumentStatus,
    StaffRefetchOutcome,
    StaffResendOutcome,
    StaffUploadOutcome,
)

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


def get_baa_block_reason(organization: Organization, impersonated: bool) -> BaaBlockReason | None:
    return logic.get_baa_block_reason(organization, impersonated)


def has_signed_baa(organization_id: UUID) -> bool:
    """
    True once the organization has a countersigned BAA on file. This is the
    standing HIPAA gate: it decides whether AI training stays locked off, so it
    must read the signature state rather than a cached flag.

    One query per call. Use `annotate_signed_baa` when serializing a list, and
    keep this for a single organization and for validating a write.
    """
    return logic.has_signed_baa(organization_id)


def annotate_signed_baa(queryset: QuerySet[Organization]) -> QuerySet[Organization]:
    """
    Add the signed-BAA flag to an Organization queryset as `SIGNED_BAA_ANNOTATION`,
    so serializing N organizations costs one query rather than N.
    """
    return logic.annotate_signed_baa(queryset)


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
    staff-only (`delete_as_staff` skips this guard and calls
    `logic.delete_document` with `strict_pandadoc=False`).

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


def list_for_staff(organization_id: UUID) -> list[contracts.StaffLegalDocument]:
    return [
        contracts.StaffLegalDocument(
            id=document.id,
            document_type=document.document_type,
            status=document.status,
            signed_pdf_stored=document.signed_pdf_stored,
            has_pandadoc_envelope=bool(document.pandadoc_document_id),
            created_at=document.created_at,
        )
        for document in logic.list_for_organization(organization_id)
    ]


def can_refetch_signed_pdf(document: contracts.StaffLegalDocument) -> bool:
    # PandaDoc only has a final PDF for a completed envelope. Storing anything
    # else would put an unsigned document behind the customer download link.
    return document.status == LegalDocumentStatus.SIGNED and document.has_pandadoc_envelope


def can_resend_signing_email(document: contracts.StaffLegalDocument) -> bool:
    return document.status != LegalDocumentStatus.SIGNED and document.has_pandadoc_envelope


def refetch_signed_pdf(document_id: UUID, organization_id: UUID) -> StaffRefetchOutcome:
    """
    Pull the document PandaDoc serves right now and overwrite the stored copy.
    Recovers a row whose archive job failed every retry, and refreshes a copy
    that no longer matches PandaDoc, for example after a counter-signature.
    """
    document = logic.get_for_organization(document_id, organization_id)
    if document is None:
        return StaffRefetchOutcome.NOT_FOUND
    if document.status != LegalDocumentStatus.SIGNED or not document.pandadoc_document_id:
        return StaffRefetchOutcome.UNAVAILABLE
    if not logic.download_and_store_signed_pdf(document):
        return StaffRefetchOutcome.FAILED
    logic.mark_signed_pdf_stored(document)
    return StaffRefetchOutcome.STORED


def resend_signing_email(document_id: UUID, organization_id: UUID) -> StaffResendOutcome:
    """
    Recovery path for an envelope stranded because the `document.draft` webhook
    that normally triggers the send was missed. The send is idempotent on
    PandaDoc's side, so the signer gets their link without a delete and regenerate.
    """
    document = logic.get_for_organization(document_id, organization_id)
    if document is None:
        return StaffResendOutcome.NOT_FOUND
    if document.status == LegalDocumentStatus.SIGNED or not document.pandadoc_document_id:
        return StaffResendOutcome.NOTHING_TO_SEND
    if not logic.send_pandadoc_envelope(document):
        return StaffResendOutcome.FAILED
    return StaffResendOutcome.SENT


def get_organization_id_for_staff(document_id: UUID) -> UUID | None:
    """The organization of a document, for staff links that only carry the document ID."""
    document = logic.get_by_id(document_id)
    return document.organization_id if document is not None else None


def uploadable_document_types(documents: list[contracts.StaffLegalDocument]) -> list[str]:
    """The document types an organization has no document of yet, since it can hold one of each."""
    taken = {document.document_type for document in documents}
    return [document_type.value for document_type in DocumentType if document_type.value not in taken]


def upload_signed_document_as_staff(upload: contracts.StaffSignedDocumentUpload, pdf: IO[bytes]) -> StaffUploadOutcome:
    try:
        logic.create_signed_document_from_upload(
            organization_id=upload.organization_id,
            created_by_id=upload.created_by_id,
            document_type=upload.document_type,
            company_name=upload.company_name,
            company_address=upload.company_address,
            representative_email=upload.representative_email,
            pdf=pdf,
        )
    except IntegrityError:
        return StaffUploadOutcome.ALREADY_EXISTS
    except logic.SignedPdfUploadFailed:
        return StaffUploadOutcome.STORAGE_FAILED
    return StaffUploadOutcome.STORED


def delete_as_staff(document_id: UUID, organization_id: UUID) -> bool:
    """
    Staff delete, including signed documents, which the self-serve delete refuses.
    The PandaDoc void and the PDF cleanup are best effort here, so a PandaDoc
    outage cannot block staff. Returns False when the document does not exist.
    """
    document = logic.get_for_organization(document_id, organization_id)
    if document is None:
        return False
    logic.delete_document(document)
    return True


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


def accept_pandadoc_event(delivery: WebhookDelivery) -> None:
    """The inbound PandaDoc webhook enters legal_documents here, so its consumer needs no internal import."""
    webhooks.accept_pandadoc_event(delivery)


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
    logic.schedule_pdf_archive(document, delay_seconds=delay_seconds)
    return True


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


def _time_since_touched(document: LegalDocument) -> timedelta:
    # updated_at is nullable on the model.
    return timezone.now() - (document.updated_at or document.created_at)


def _recreate_lost_envelope(document: LegalDocument) -> bool:
    """
    PandaDoc no longer has the envelope for a row still out for signature, so
    the customer can never be emailed from it. Confirms the envelope is truly
    gone before superseding it, records that in error tracking, then creates a
    fresh envelope from the row's own data.
    """
    if not logic.confirm_pandadoc_envelope_gone(document):
        return False
    lost_pandadoc_document_id = document.pandadoc_document_id
    logger.warning(
        "legal_document_pandadoc_envelope_lost",
        document_id=str(document.id),
        pandadoc_document_id=lost_pandadoc_document_id,
    )
    capture_exception(
        Exception("PandaDoc envelope no longer exists for a legal document still out for signature"),
        additional_properties={
            "legal_document_id": str(document.id),
            "pandadoc_document_id": lost_pandadoc_document_id,
            "organization_id": str(document.organization_id),
        },
    )
    return logic.retry_pandadoc_envelope(document)


def reconcile_pending_signatures() -> contracts.LegalDocumentReconcileResult:
    """
    Safety net for the whole completion path. Polls PandaDoc for every row we
    still think is out for signature and marks the completed ones — recovering
    dropped, throttled, or 204'd `document.completed` webhooks and clearing the
    backlog. Also re-sends envelopes stranded in `document.draft` — PandaDoc's
    send call can 409 and never dispatch the signing email — and re-enqueues
    the archive for signed rows whose PDF never landed.

    Each row is processed independently: `list_pending_signature_documents` is
    ordered oldest-first, so one row that deterministically errors (a bad
    PandaDoc response, a DB hiccup) must not block every row behind it on every
    15-minute tick. Also retries envelope creation for rows whose PandaDoc
    envelope disappeared or was never created.
    """
    newly_signed = 0
    drafts_resent = 0
    envelopes_recreated = 0
    errors = 0
    pending_seen = 0
    # PandaDoc allows 100 downloads a minute across the whole account, shared with
    # live signings. Staggering one archive per second keeps a backlog drain from
    # starving a customer signing right now, and holds regardless of worker count.
    scheduled_archives = 0
    recreate_attempts = 0
    signed_this_run: set[UUID] = set()
    # One scoped client for the whole loop, not one per row: this runs in a Celery
    # worker, where the global client's background flush may never run before the
    # process exits, and the scoped client blocks for seconds on setup and flush.
    # Losing these events would hide whether the sweep is recovering anything.
    with ph_scoped_capture() as capture:
        for document in logic.list_pending_signature_documents():
            pending_seen += 1
            try:
                pandadoc_status = logic.get_pandadoc_document_status(document)
                if pandadoc_status == logic.PANDADOC_COMPLETED_STATUS:
                    if _try_mark_signed_and_schedule_archive(
                        document, capture=capture, delay_seconds=scheduled_archives
                    ):
                        newly_signed += 1
                        scheduled_archives += 1
                        signed_this_run.add(document.id)
                elif (
                    pandadoc_status == logic.PANDADOC_DRAFT_STATUS
                    and _time_since_touched(document) >= logic.RECONCILE_DRAFT_MIN_AGE
                ):
                    if logic.send_pandadoc_envelope(document):
                        drafts_resent += 1
                    else:
                        errors += 1
                elif (
                    pandadoc_status == logic.PANDADOC_ENVELOPE_MISSING
                    and _time_since_touched(document) >= logic.RECONCILE_RECREATE_MIN_AGE
                    and recreate_attempts < logic.RECONCILE_MAX_RECREATES_PER_RUN
                ):
                    if logic.claim_pandadoc_envelope_retry(document):
                        recreate_attempts += 1
                        if _recreate_lost_envelope(document):
                            envelopes_recreated += 1
                        else:
                            errors += 1
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

    for document in logic.list_pending_documents_missing_envelope():
        if recreate_attempts >= logic.RECONCILE_MAX_RECREATES_PER_RUN:
            logger.warning(
                "legal_document_reconcile_recreate_cap_reached",
                attempted=recreate_attempts,
                cap=logic.RECONCILE_MAX_RECREATES_PER_RUN,
            )
            break
        if _time_since_touched(document) < logic.RECONCILE_RECREATE_MIN_AGE:
            continue
        try:
            if not logic.claim_pandadoc_envelope_retry(document):
                continue
            recreate_attempts += 1
            if logic.retry_pandadoc_envelope(document):
                envelopes_recreated += 1
            else:
                errors += 1
        except Exception as exc:
            errors += 1
            logger.exception("legal_document_reconcile_missing_envelope_row_failed", document_id=str(document.id))
            capture_exception(exc, additional_properties={"legal_document_id": str(document.id)})

    # Rows this run just signed and already scheduled an archive for above.
    # excluding them here is what keeps the archive from being `.delay()`'d twice.
    archives_requeued = 0
    for document in logic.list_signed_documents_missing_pdf(exclude_ids=signed_this_run):
        try:
            logic.schedule_pdf_archive(document, delay_seconds=scheduled_archives)
            archives_requeued += 1
            scheduled_archives += 1
        except Exception as exc:
            errors += 1
            logger.exception("legal_document_reconcile_archive_row_failed", document_id=str(document.id))
            capture_exception(exc, additional_properties={"legal_document_id": str(document.id)})

    return contracts.LegalDocumentReconcileResult(
        newly_signed=newly_signed,
        archives_requeued=archives_requeued,
        drafts_resent=drafts_resent,
        envelopes_recreated=envelopes_recreated,
        errors=errors,
    )
