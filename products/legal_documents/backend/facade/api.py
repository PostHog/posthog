"""
Facade for legal_documents.

This is the ONLY module other products (and the presentation layer) are allowed
to import. Accepts frozen dataclasses as input, returns frozen dataclasses as
output, and never leaks ORM instances or QuerySets across the boundary.
"""

from uuid import UUID

from posthog.models.organization import Organization

from .. import logic
from ..logic.pandadoc import verify_webhook_signature as _verify_pandadoc_webhook_signature
from . import contracts
from .enums import LegalDocumentStatus


def _to_dto(doc) -> contracts.LegalDocumentDTO:
    creator = doc.created_by
    return contracts.LegalDocumentDTO(
        id=doc.id,
        document_type=doc.document_type,
        company_name=doc.company_name,
        representative_email=doc.representative_email,
        status=doc.status,
        signed_document_url=doc.signed_document_url,
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

    # Fire and forget: PandaDoc + Slack never block the response. If PandaDoc
    # fails we still 201 — ops gets a Slack ping (best-effort) and the row is
    # left without a pandadoc_document_id for the admin "resend" action later.
    logic.submit_to_pandadoc(document)
    logic.notify_slack_on_submit(document)
    logic.fire_legal_document_submitted_event(document, distinct_id=data.distinct_id)

    return _to_dto(document)


def mark_signed_by_pandadoc_document_id(
    *,
    pandadoc_document_id: str,
    signed_document_url: str,
    template_id: str,
) -> contracts.LegalDocumentDTO | None:
    """
    Entry point from the PandaDoc webhook. The caller must have already
    verified the HMAC signature on the raw body; this function:

    - Looks up the row by the PandaDoc document uuid (no IDOR surface: unknown ids 404).
    - Double-checks the template matches the stored document variant, to guard
      against misconfigured PandaDoc templates flipping the wrong row.
    - Flips status to signed, fires analytics + Slack.

    Idempotent: if the row is already signed we return the existing DTO
    without touching the URL or re-firing Slack/analytics. PandaDoc can
    replay the same webhook (retries, multi-instance fan-out, out-of-order
    delivery after a manual admin paste) — the first write wins.
    """
    document = logic.get_by_pandadoc_document_id(pandadoc_document_id)
    if document is None:
        return None
    if not logic.template_id_matches_document(document, template_id):
        return None
    if document.signed_document_url or document.status == LegalDocumentStatus.SIGNED:
        return _to_dto(document)
    document = logic.mark_document_signed(document, signed_document_url)
    logic.notify_slack_on_signed(document)
    logic.fire_legal_document_signed_event(document)
    return _to_dto(document)
