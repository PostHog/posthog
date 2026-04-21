"""
Contract types for legal_documents.

Stable, framework-free frozen dataclasses that define what this product
exposes to the rest of the codebase. No Django imports.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class LegalDocumentCreator:
    first_name: str
    email: str


@dataclass(frozen=True)
class LegalDocumentDTO:
    id: UUID
    document_type: str
    company_name: str
    representative_name: str
    representative_email: str
    status: str
    signed_document_url: str
    created_by: LegalDocumentCreator | None
    created_at: datetime


@dataclass(frozen=True)
class CreateLegalDocumentInput:
    """Input for creating a new legal document. organization/user are injected by the view."""

    organization_id: UUID
    created_by_id: int
    # Distinct ID of the submitting user, used to fire the PostHog event on create.
    distinct_id: str
    document_type: str
    company_name: str
    company_address: str
    representative_name: str
    representative_title: str
    representative_email: str
    dpa_mode: str
