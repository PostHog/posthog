"""
Facade for legal_documents.

This is the ONLY module other products (and the presentation layer) are allowed
to import. Accepts frozen dataclasses as input, returns frozen dataclasses as
output, and never leaks ORM instances or QuerySets across the boundary.
"""

from __future__ import annotations

from uuid import UUID

from posthog.models.organization import Organization

from .. import logic
from ..logic.pandadoc import verify_webhook_signature as _verify_pandadoc_webhook_signature
from ..models import LegalDocument
from . import contracts
from .enums import LegalDocumentStatus


class LegalDocumentDownloadFailed(Exception):
    """
    Raised when we own a row but couldn't pull the signed PDF from PandaDoc /
    stash it in object storage. The webhook handler surfaces this as a 5xx so
    PandaDoc retries; the underlying exception has already been logged +
    captured at the source.
    """


def _to_dto(doc: LegalDocument) -> contracts.LegalDocumentDTO:
    creator = doc.created_by
    return contracts.LegalDocumentDTO(
        id=doc.id,
        document_type=doc.document_type,
        company_name=doc.company_name,
        representative_email=doc.representative_email,
        status=doc.status,
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
    if document is None or document.status != LegalDocumentStatus.SIGNED:
        return None
    return logic.get_signed_pdf_presigned_url(document)


def has_qualifying_baa_addon(organization: Organization) -> bool:
    return logic.has_qualifying_baa_addon(organization)


def verify_pandadoc_webhook_signature(*, secret: str, body: bytes, signature: str) -> bool:
    """Passthrough so the presentation layer never reaches past the facade."""
    return _verify_pandadoc_webhook_signature(secret=secret, body=body, signature=signature)


def exists_for_organization_and_type(organization_id: UUID, document_type: str) -> bool:
    return logic.exists_for_organization_and_type(organization_id, document_type)


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
    # the `document.draft` webhook triggers the actual send + Slack ping via
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
    email and fire the Slack "submitted" notification.

    Idempotent: if the envelope has already been dispatched (row is already
    signed, or the send call fails because PandaDoc has moved past draft)
    we quietly skip the side effects.
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
    sent = logic.send_pandadoc_envelope(document)
    if sent:
        logic.notify_slack_on_submit(document)
    return _to_dto(document)


def mark_signed_by_pandadoc_document_id(
    *,
    pandadoc_document_id: str,
    template_id: str,
) -> contracts.LegalDocumentDTO | None:
    """
    Entry point from the PandaDoc webhook. The caller must have already
    verified the HMAC signature on the raw body; this function:

    - Looks up the row by the PandaDoc document uuid (no IDOR surface: unknown ids 404).
    - Double-checks the template matches the stored document variant, to guard
      against misconfigured PandaDoc templates flipping the wrong row.
    - Downloads the signed PDF from PandaDoc and stashes it in object storage.
    - Flips status to signed, fires analytics + Slack.

    Idempotent: if the row is already signed we return the existing DTO
    without re-downloading or re-firing Slack/analytics. If the download or
    upload fails we leave the row unsigned and return None so the webhook
    handler can surface 5xx; PandaDoc will retry.
    """
    document = logic.get_by_pandadoc_document_id(pandadoc_document_id)
    if document is None:
        return None
    if not logic.template_id_matches_document(document, template_id):
        return None
    if document.status == LegalDocumentStatus.SIGNED:
        return _to_dto(document)
    if not logic.download_and_store_signed_pdf(document):
        raise LegalDocumentDownloadFailed(f"Failed to retrieve signed PDF for legal_document {document.id}")
    document = logic.mark_document_signed(document)
    logic.notify_slack_on_signed(document)
    logic.fire_legal_document_signed_event(document)
    return _to_dto(document)
