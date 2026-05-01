"""Exported enums and constants for legal_documents."""

from enum import StrEnum


class DocumentType(StrEnum):
    BAA = "BAA"
    DPA = "DPA"


class LegalDocumentStatus(StrEnum):
    SUBMITTED_FOR_SIGNATURE = "submitted_for_signature"
    SIGNED = "signed"
