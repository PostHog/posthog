from enum import StrEnum

from temporalio.exceptions import ApplicationError, ApplicationErrorCategory

from products.replay_vision.backend.error_kinds import FailureKind, IneligibleSessionKind

__all__ = [
    "INELIGIBLE_SESSION_ERROR_TYPE",
    "SCANNER_FAILURE_ERROR_TYPE",
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
        # A retryable kind (a transient provider outage) is an expected, non-defect failure: mark it BENIGN so
        # Temporal logs it at DEBUG and the PostHog interceptor skips reporting it to error tracking.
        category = ApplicationErrorCategory.UNSPECIFIED if non_retryable else ApplicationErrorCategory.BENIGN
        super().__init__(message, str(kind), type=type, non_retryable=non_retryable, category=category)
        self.kind = kind


class IneligibleSessionError(_KindedApplicationError):
    """The session doesn't qualify for analysis. Surfaced as ObservationStatus.INELIGIBLE, not FAILED."""

    def __init__(self, message: str, *, kind: IneligibleSessionKind) -> None:
        super().__init__(message, kind=kind, type=INELIGIBLE_SESSION_ERROR_TYPE)


class ScannerFailureError(_KindedApplicationError):
    """A classified workflow failure. Surfaced as ObservationStatus.FAILED with the kind label on the frontend."""

    def __init__(self, message: str, *, kind: FailureKind) -> None:
        super().__init__(message, kind=kind, type=SCANNER_FAILURE_ERROR_TYPE, non_retryable=not kind.is_retryable)
