"""Terminal-observation error taxonomy; sited outside `temporal/` so the model can import it without temporalio."""

from enum import StrEnum


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

    @property
    def is_benign(self) -> bool:
        """An expected terminal outcome caused by the model, not our code: the observation lands in FAILED with a
        user-facing reason, so it must not be reported to error tracking as if it were a defect."""
        return self is FailureKind.VALIDATION_FAILED


# Shared by the model field and the API serializer so the documented vocabulary can't drift from the enums.
ERROR_REASON_HELP_TEXT = (
    "Populated on terminal non-success statuses; formatted as `kind:human-readable message`. "
    f"For `ineligible`, kind is one of {' / '.join(IneligibleSessionKind)}. "
    f"For `failed`, kind is one of {' / '.join(FailureKind)}."
)
