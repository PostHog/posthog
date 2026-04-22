"""Exported enums and constants for legal_documents."""

from enum import StrEnum


class DocumentType(StrEnum):
    BAA = "BAA"
    DPA = "DPA"


class DPAMode(StrEnum):
    PRETTY = "pretty"
    LAWYER = "lawyer"
    FAIRYTALE = "fairytale"
    TSWIFT = "tswift"


class LegalDocumentStatus(StrEnum):
    SUBMITTED_FOR_SIGNATURE = "submitted_for_signature"
    SIGNED = "signed"


# DPA modes that the API accepts on submit — fairytale and tswift are preview-only.
DPA_SUBMITTABLE_MODES = frozenset({DPAMode.PRETTY, DPAMode.LAWYER})
