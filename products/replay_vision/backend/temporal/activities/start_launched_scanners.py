"""Starts experiment scanners that are still waiting for an experiment that has already launched.

The launch signal starts them, but its receiver must never fail a launch, so a failure there is only
logged. The launch has committed by then, and a relaunch does not send the signal again, so without
this the scanner stays off for good.
"""

from temporalio import activity

from posthog.sync import database_sync_to_async

from products.replay_vision.backend.experiment_launch import start_scanners_of_launched_experiments
from products.replay_vision.backend.temporal.constants import REAPER_OP_TIMEOUT
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.query_budget import bounded_queries


@database_sync_to_async
def _start_launched_scanners() -> int:
    with bounded_queries(REAPER_OP_TIMEOUT):
        return start_scanners_of_launched_experiments()


@activity.defn
@track_activity()
async def start_launched_scanners_activity() -> int:
    started = await _start_launched_scanners()
    if started:
        activity.logger.info("Started scanners whose experiment launched", extra={"started": started})
    return started
