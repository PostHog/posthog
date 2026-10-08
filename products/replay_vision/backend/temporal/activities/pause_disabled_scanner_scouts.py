from temporalio import activity

from posthog.sync import database_sync_to_async

from products.replay_vision.backend.scout_wind_down import pause_scouts_after_final_run
from products.replay_vision.backend.temporal.constants import REAPER_OP_TIMEOUT
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.query_budget import bounded_queries


@database_sync_to_async
def _pause_disabled_scanner_scouts() -> int:
    with bounded_queries(REAPER_OP_TIMEOUT):
        return pause_scouts_after_final_run()


@activity.defn
@track_activity()
async def pause_disabled_scanner_scouts_activity() -> int:
    paused = await _pause_disabled_scanner_scouts()
    if paused:
        activity.logger.info("Paused scouts of turned-off scanners", extra={"paused": paused})
    return paused
