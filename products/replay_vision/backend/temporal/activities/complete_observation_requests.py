"""Completes programmatic scan requests once every session has settled, and announces each one."""

from temporalio import activity

from posthog.sync import database_sync_to_async

from products.replay_vision.backend.observation_requests import complete_settled_requests
from products.replay_vision.backend.temporal.constants import REAPER_OP_TIMEOUT
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.query_budget import bounded_queries


@database_sync_to_async
def _complete_observation_requests() -> int:
    with bounded_queries(REAPER_OP_TIMEOUT):
        return complete_settled_requests()


@activity.defn
@track_activity()
async def complete_observation_requests_activity() -> int:
    completed = await _complete_observation_requests()
    if completed:
        activity.logger.info("Completed observation requests", extra={"completed": completed})
    return completed
