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
    representative_email: str
    status: str
    # True once the signed PDF is in object storage. A signed row can still have
    # this False for a short window while the archive job runs, so the UI knows
    # to hold the download link back until the file lands.
    signed_pdf_stored: bool
    created_by: LegalDocumentCreator | None
    created_at: datetime


@dataclass(frozen=True)
class LegalDocumentReconcileResult:
    """Outcome of one reconciliation sweep, for logging and tests."""

    newly_signed: int
    archives_requeued: int
    drafts_resent: int
    errors: int


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
    representative_email: str
