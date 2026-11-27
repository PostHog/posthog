from posthog.dataclasses import frozen

SCHEDULED_RECALCULATION_WORKFLOW_NAME = "experiment-scheduled-recalculation-workflow"


@frozen
class ScheduledRecalculationStartResult:
    """Outcome of one experiment's start attempt, for the coordinator's summary counts."""

    experiment_id: int
    started: bool
    recalculation_id: str | None = None
    skip_reason: str | None = None
