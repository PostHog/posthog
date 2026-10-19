"""Starts waiting scan requests whose sessions have ended, then completes and announces the settled ones."""

import time

from temporalio import activity

from posthog.sync import database_sync_to_async

from products.replay_vision.backend.temporal.constants import COMPLETE_OBSERVATION_REQUESTS_TIMEOUT
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.query_budget import bounded_queries, query_deadline


@database_sync_to_async
def _complete_observation_requests() -> int:
    # Deferred: observation_requests reaches scanner_config, which imports this package while it loads.
    from products.replay_vision.backend.observation_requests import (  # noqa: PLC0415
        COMPLETION_STAMP_HEADROOM_SECONDS,
        COMPLETION_SWEEP_BUDGET_SECONDS,
        complete_settled_requests,
        start_waiting_requests,
    )

    # Isolated so a failure in one sweep still lets the other run; each also keeps to its own time budget.
    deadline = query_deadline(COMPLETE_OBSERVATION_REQUESTS_TIMEOUT)
    with bounded_queries(COMPLETE_OBSERVATION_REQUESTS_TIMEOUT):
        try:
            start_waiting_requests()
        except Exception:
            activity.logger.exception("Starting waiting observation requests failed")
        # A start sweep that overran leaves less than the full budget, and a canceled stamp re-announces its page.
        remaining = deadline - time.time() - COMPLETION_STAMP_HEADROOM_SECONDS
        return complete_settled_requests(budget_seconds=min(COMPLETION_SWEEP_BUDGET_SECONDS, remaining))


@activity.defn
@track_activity()
async def complete_observation_requests_activity() -> int:
    completed = await _complete_observation_requests()
    if completed:
        activity.logger.info("Completed observation requests", extra={"completed": completed})
    return completed
