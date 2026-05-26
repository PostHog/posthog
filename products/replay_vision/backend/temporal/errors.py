from enum import StrEnum

from temporalio.exceptions import ApplicationError

# String survives Temporal's ActivityError wrapping via ApplicationError.type, so the
# workflow can dispatch on it without parsing exception messages.
INELIGIBLE_SESSION_ERROR_TYPE = "IneligibleSession"


class IneligibleSessionKind(StrEnum):
    """Reason a scanner couldn't be applied to a session — not a failure, the session doesn't qualify."""

    NO_RECORDING = "no_recording"
    TOO_SHORT = "too_short"
    TOO_INACTIVE = "too_inactive"
    TOO_LONG = "too_long"
    NO_EVENTS = "no_events"


class IneligibleSessionError(ApplicationError):
    """The session doesn't qualify for analysis. Surfaced as ObservationStatus.INELIGIBLE, not FAILED."""

    def __init__(self, message: str, *, kind: IneligibleSessionKind) -> None:
        # `details=(kind,)` is the canonical way to attach typed payload to an ApplicationError
        # that the workflow can read off `cause.details` after Temporal's ActivityError wrap.
        super().__init__(message, str(kind), type=INELIGIBLE_SESSION_ERROR_TYPE, non_retryable=True)
        self.kind = kind


SCANNER_FAILURE_ERROR_TYPE = "ScannerFailure"


class FailureKind(StrEnum):
    """User-facing classification of a failed observation; drives the frontend description + advice."""

    PROVIDER_TRANSIENT = "provider_transient"  # AI provider outage / network — retry usually helps
    PROVIDER_REJECTED = "provider_rejected"  # AI provider couldn't process the video — won't recover
    RASTERIZATION_FAILED = "rasterization_failed"  # Rasterizer couldn't render this recording — known issue
    VALIDATION_FAILED = "validation_failed"  # LLM output didn't match the scanner schema after internal retries
    INTERNAL_ERROR = "internal_error"  # Unclassified / bug paths — user can't fix


class ScannerFailureError(ApplicationError):
    """A classified workflow failure. Surfaced as ObservationStatus.FAILED with the kind label on the frontend."""

    def __init__(self, message: str, *, kind: FailureKind, non_retryable: bool = True) -> None:
        super().__init__(message, str(kind), type=SCANNER_FAILURE_ERROR_TYPE, non_retryable=non_retryable)
        self.kind = kind
