import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from django.conf import settings

import structlog

from posthog.temporal.common.worker import DEFAULT_MAX_CONCURRENT_TASKS

if TYPE_CHECKING:
    from products.error_tracking.backend.logic.issue_summaries import (
        IssueSummaryOutcome,
        IssueSummaryResult,
        IssueSummaryTrigger,
    )

logger = structlog.get_logger(__name__)

MIN_ISSUE_SUMMARY_WORKER_SLOTS = 3
# Alert dispatch, embedding, severity inference and tagging share this worker's activity slots.
MIN_NON_SUMMARY_WORKER_SLOTS = 2


def issue_summary_worker_slot_count(max_concurrent_activities: int) -> int:
    """A quarter of the activity slots, raised to a floor that a small worker still leaves room for."""
    floor = min(MIN_ISSUE_SUMMARY_WORKER_SLOTS, max_concurrent_activities - MIN_NON_SUMMARY_WORKER_SLOTS)
    return max(1, floor, max_concurrent_activities // 4)


# A summary holds an activity slot for the whole model call.
ISSUE_SUMMARY_WORKER_SLOTS = threading.BoundedSemaphore(
    issue_summary_worker_slot_count(settings.MAX_CONCURRENT_ACTIVITIES or DEFAULT_MAX_CONCURRENT_TASKS)
)


def generate_summary_on_worker(
    team_id: int, issue_id: str, trigger: "IssueSummaryTrigger", generate: Callable[[], "IssueSummaryResult"]
) -> "IssueSummaryOutcome":
    """Run a lifecycle summary generation when the flag is on, a worker summary slot is free and the AI features gate
    allows it."""
    # issue_summaries imports the lifecycle rendering module, whose package imports the activities that call this.
    from products.error_tracking.backend.logic.issue_summaries import (  # noqa: PLC0415
        IssueSummaryOutcome,
        gate_generation,
        issue_summaries_enabled,
        record_outcome,
    )

    # The flag reads no database, so a team outside it takes no slot and sends no event.
    if not issue_summaries_enabled(team_id):
        return IssueSummaryOutcome.DISABLED
    # Skip instead of wait, because a waiting activity still holds its slot. The issue then gets no summary.
    if not ISSUE_SUMMARY_WORKER_SLOTS.acquire(blocking=False):
        logger.warning("error_tracking_issue_summary_worker_busy", team_id=team_id, issue_id=issue_id, trigger=trigger)
        record_outcome(team_id, issue_id, trigger, IssueSummaryOutcome.RATE_LIMITED)
        return IssueSummaryOutcome.RATE_LIMITED
    try:
        # The gate reads Postgres and Redis, so a stall holds only the summary share of the activity slots.
        if (blocked := gate_generation(team_id, issue_id, trigger)) is not None:
            return blocked
        return generate().outcome
    finally:
        ISSUE_SUMMARY_WORKER_SLOTS.release()
