from enum import StrEnum

from temporalio.exceptions import ApplicationError

# Strings survive Temporal's ActivityError wrapping via ApplicationError.type, so the
# workflow can dispatch on them without parsing exception messages.
INELIGIBLE_SESSION_ERROR_TYPE = "IneligibleSession"
SCANNER_FAILURE_ERROR_TYPE = "ScannerFailure"


class IneligibleSessionKind(StrEnum):
    """Reason a scanner couldn't be applied to a session — not a failure, the session doesn't qualify."""

    NO_RECORDING = "no_recording"
    TOO_SHORT = "too_short"
    TOO_INACTIVE = "too_inactive"
    TOO_LONG = "too_long"
    NO_EVENTS = "no_events"


class FailureKind(StrEnum):
    """User-facing classification of a failed observation; drives the frontend description + advice."""

    PROVIDER_TRANSIENT = "provider_transient"  # AI provider outage / network — retry usually helps
    PROVIDER_REJECTED = "provider_rejected"  # AI provider couldn't process the video — won't recover
    RASTERIZATION_FAILED = "rasterization_failed"  # Rasterizer couldn't render this recording — known issue
    VALIDATION_FAILED = "validation_failed"  # LLM output didn't match the scanner schema after internal retries
    INTERNAL_ERROR = "internal_error"  # Unclassified / bug paths — user can't fix
    ORPHANED = "orphaned"  # Workflow died without reaching a terminal state (timeout, terminate); set by the reaper

    @property
    def is_retryable(self) -> bool:
        return self is FailureKind.PROVIDER_TRANSIENT


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
    """A classified workflow failure. Surfaced as ObservationStatus.FAILED with the kind label on the frontend."""

    def __init__(self, message: str, *, kind: FailureKind) -> None:
        super().__init__(message, kind=kind, type=SCANNER_FAILURE_ERROR_TYPE, non_retryable=not kind.is_retryable)
