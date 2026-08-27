"""Terminal-observation error taxonomy; sited outside `temporal/` so the model can import it without temporalio."""

from enum import StrEnum


class IneligibleSessionKind(StrEnum):
    """Reason a scanner couldn't be applied to a session — not a failure, the session doesn't qualify."""

    NO_RECORDING = "no_recording"
    TOO_SHORT = "too_short"
    TOO_INACTIVE = "too_inactive"
    TOO_LONG = "too_long"
    NO_EVENTS = "no_events"
    # Replay metadata exists but the snapshot blocks hold nothing renderable, so there is no video to analyze.
    # Usually a property of the recording, but it can be a timing artifact (snapshots still ingesting, a
    # backfill landing late), so the retry endpoint accepts ineligible rows and the UI offers a retry here.
    NO_SNAPSHOTS = "no_snapshots"
    # The recording's snapshot blocks exceed the rasterizer's size cap, so the render is refused before it starts.
    # This is a fixed property of the recording, so no retry can make the scan succeed.
    TOO_LARGE = "too_large"


class FailureKind(StrEnum):
    """User-facing classification of a failed observation; drives the frontend description + advice."""

    PROVIDER_TRANSIENT = "provider_transient"  # AI provider outage / rate limit / network; retry usually helps
    PROVIDER_REJECTED = "provider_rejected"  # AI provider couldn't process the video — won't recover
    RASTERIZATION_FAILED = "rasterization_failed"  # Rasterizer couldn't render this recording — known issue
    VALIDATION_FAILED = "validation_failed"  # LLM output didn't match the scanner schema after internal retries
    INFRA_TRANSIENT = "infra_transient"  # PostHog-side dependency was slow or at capacity; retry usually helps
    INTERNAL_ERROR = "internal_error"  # Unclassified / bug paths — user can't fix
    ORPHANED = "orphaned"  # Workflow died without reaching a terminal state (timeout, terminate); set by the reaper

    @property
    def is_retryable(self) -> bool:
        """Whether Temporal should re-run the activity that raised this. Only the two transient kinds recover on their own."""
        return self in (FailureKind.PROVIDER_TRANSIENT, FailureKind.INFRA_TRANSIENT)


# Shared by the model field and the API serializer so the documented vocabulary can't drift from the enums.
ERROR_REASON_HELP_TEXT = (
    "Populated on terminal non-success statuses; formatted as `kind:human-readable message`. "
    f"For `ineligible`, kind is one of {' / '.join(IneligibleSessionKind)}. "
    f"For `failed`, kind is one of {' / '.join(FailureKind)}."
)
