from enum import StrEnum

from temporalio.exceptions import ApplicationError

from posthog.temporal.common.errors import NonReportableError

from products.replay_vision.backend.error_kinds import FailureKind, IneligibleSessionKind

__all__ = [
    "INELIGIBLE_SESSION_ERROR_TYPE",
    "SCANNER_FAILURE_ERROR_TYPE",
    "ConsentWithdrawnError",
    "FailureKind",
    "IneligibleSessionError",
    "IneligibleSessionKind",
    "ScannerFailureError",
]

# Strings survive Temporal's ActivityError wrapping via ApplicationError.type, so the
# workflow can dispatch on them without parsing exception messages.
INELIGIBLE_SESSION_ERROR_TYPE = "IneligibleSession"
SCANNER_FAILURE_ERROR_TYPE = "ScannerFailure"


class _KindedApplicationError(ApplicationError):
    """ApplicationError carrying a typed `kind` payload that survives Temporal's serialization.

    `details=(kind,)` is the canonical way to attach a typed payload an outer workflow can read off
    `cause.details` after Temporal wraps the activity raise in ActivityError.
    """

    def __init__(self, message: str, *, kind: StrEnum, type: str, non_retryable: bool = True) -> None:
        super().__init__(message, str(kind), type=type, non_retryable=non_retryable)
        self.kind = kind


class IneligibleSessionError(_KindedApplicationError):
    """The session doesn't qualify for analysis. Surfaced as ObservationStatus.INELIGIBLE, not FAILED."""

    def __init__(self, message: str, *, kind: IneligibleSessionKind) -> None:
        super().__init__(message, kind=kind, type=INELIGIBLE_SESSION_ERROR_TYPE)


class ScannerFailureError(_KindedApplicationError):
    """A classified workflow failure. Surfaced as ObservationStatus.FAILED with the kind label on the frontend.

    A retryable kind (provider/infra transient, undecodable render upload) recovers on Temporal's own retry,
    so reporting each pre-recovery attempt to error tracking is pure noise — a single dropped connection to
    the provider fingerprinted three separate live issues that all recovered. Retryable failures are therefore
    minted as `_RetryableScannerFailureError`, which the Temporal interceptor skips via `NonReportableError`;
    terminal failures stay plain and reportable.
    """

    def __new__(cls, message: str, *, kind: FailureKind) -> "ScannerFailureError":
        target = _RetryableScannerFailureError if cls is ScannerFailureError and kind.is_retryable else cls
        return super().__new__(target)

    def __init__(self, message: str, *, kind: FailureKind) -> None:
        super().__init__(message, kind=kind, type=SCANNER_FAILURE_ERROR_TYPE, non_retryable=not kind.is_retryable)


class _RetryableScannerFailureError(ScannerFailureError, NonReportableError):
    """A ScannerFailureError whose kind is retryable. The `NonReportableError` marker keeps Temporal's retry
    attempts out of error tracking; nothing else distinguishes it from its parent."""


class _ConsentKind(StrEnum):
    # Kept out of IneligibleSessionKind on purpose: this is a policy abort, not a session-eligibility reason,
    # so it stays off the DB `error_reason` help text / OpenAPI taxonomy. Surfaced as INELIGIBLE all the same.
    NO_AI_CONSENT = "no_ai_consent"


class ConsentWithdrawnError(_KindedApplicationError):
    """Org AI data-processing consent was withdrawn before an egress step. Surfaced as INELIGIBLE, never retried."""

    def __init__(self, message: str) -> None:
        super().__init__(message, kind=_ConsentKind.NO_AI_CONSENT, type=INELIGIBLE_SESSION_ERROR_TYPE)
