"""
Facade for legal_documents.

This is the ONLY module other products (and the presentation layer) are allowed
to import. Accepts frozen dataclasses as input, returns frozen dataclasses as
output, and never leaks ORM instances or QuerySets across the boundary.
"""

from uuid import UUID

from posthog.models.organization import Organization

from .. import logic
from . import contracts


def _to_dto(doc) -> contracts.LegalDocumentDTO:
    creator = doc.created_by
    return contracts.LegalDocumentDTO(
        id=doc.id,
        document_type=doc.document_type,
        company_name=doc.company_name,
        representative_name=doc.representative_name,
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


def exists_for_organization_and_type(organization_id: UUID, document_type: str) -> bool:
    return logic.exists_for_organization_and_type(organization_id, document_type)


def create_document(data: contracts.CreateLegalDocumentInput) -> contracts.LegalDocumentDTO:
    document = logic.create_document(
        organization_id=data.organization_id,
        created_by_id=data.created_by_id,
        document_type=data.document_type,
        company_name=data.company_name,
        company_address=data.company_address,
        representative_name=data.representative_name,
        representative_title=data.representative_title,
        representative_email=data.representative_email,
        dpa_mode=data.dpa_mode,
    )
    logic.fire_legal_document_event(document, distinct_id=data.distinct_id)
    return _to_dto(document)


def mark_signed_by_secret(secret: str, signed_document_url: str) -> contracts.LegalDocumentDTO | None:
    document = logic.get_by_webhook_secret(secret)
    if document is None:
        return None
    document = logic.mark_document_signed(document, signed_document_url)
    return _to_dto(document)
