"""Exported enums and constants for legal_documents."""

from enum import StrEnum


class DocumentType(StrEnum):
    BAA = "BAA"
    DPA = "DPA"
    MSA = "MSA"


class LegalDocumentStatus(StrEnum):
    SUBMITTED_FOR_SIGNATURE = "submitted_for_signature"
    SIGNED = "signed"


class BaaBlockReason(StrEnum):
    STARTUP_PROGRAM = "startup_program"
    NO_QUALIFYING_ADDON = "no_qualifying_addon"
