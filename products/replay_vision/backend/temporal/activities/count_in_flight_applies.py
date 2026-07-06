import structlog
from temporalio import activity

from posthog.temporal.common.client import async_connect

from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.sweep_types import CountInFlightAppliesInputs

logger = structlog.get_logger(__name__)


@activity.defn
@track_activity()
async def count_in_flight_applies_activity(inputs: CountInFlightAppliesInputs) -> int:
    """Count this scanner's running apply-scanner workflows (PostHogScannerId is stamped only on those).

    Fails open (returns 0) so a visibility hiccup lets the sweep proceed rather than wedging it.
    """
    query = f'PostHogScannerId = "{inputs.scanner_id}" AND ExecutionStatus = "Running"'
    try:
        client = await async_connect()
        return (await client.count_workflows(query)).count
    except Exception as exc:
        logger.warning("replay_vision.count_in_flight_failed", scanner_id=str(inputs.scanner_id), error=str(exc))
        return 0
