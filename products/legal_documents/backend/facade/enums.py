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


class StaffRefetchOutcome(StrEnum):
    STORED = "stored"
    FAILED = "failed"
    # PandaDoc only serves a final PDF for a completed envelope.
    UNAVAILABLE = "unavailable"
    NOT_FOUND = "not_found"


class StaffResendOutcome(StrEnum):
    SENT = "sent"
    FAILED = "failed"
    # The document is signed, or it has no PandaDoc envelope.
    NOTHING_TO_SEND = "nothing_to_send"
    NOT_FOUND = "not_found"
