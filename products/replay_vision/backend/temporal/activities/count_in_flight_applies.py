import structlog
from temporalio import activity

from posthog.temporal.common.client import async_connect

from products.replay_vision.backend.temporal.constants import APPLY_SCANNER_WORKFLOW_NAME
from products.replay_vision.backend.temporal.sweep_types import CountInFlightAppliesInputs

logger = structlog.get_logger(__name__)


@activity.defn
async def count_in_flight_applies_activity(inputs: CountInFlightAppliesInputs) -> int:
    """Count this scanner's currently-running apply-scanner workflows via the PostHogScannerId search attribute.

    Returns 0 if the count can't be obtained — better to let the sweep proceed than to wedge it on a
    visibility hiccup.
    """
    query = (
        f'WorkflowType = "{APPLY_SCANNER_WORKFLOW_NAME}" '
        f'AND PostHogScannerId = "{inputs.scanner_id}" '
        f'AND ExecutionStatus = "Running"'
    )
    try:
        client = await async_connect()
        result = await client.count_workflows(query)
        return result.count
    except Exception as exc:
        logger.warning("replay_vision.count_in_flight_failed", scanner_id=str(inputs.scanner_id), error=str(exc))
        return 0
