from temporalio import workflow
from temporalio.exceptions import ActivityError

from products.error_tracking.backend.temporal.lifecycle.policies import (
    SUMMARY_RETRY_POLICY,
    SUMMARY_SCHEDULE_TO_CLOSE_TIMEOUT,
    SUMMARY_START_TO_CLOSE_TIMEOUT,
)


async def execute_summary_activity(activity: str, inputs: object, *, fail_open_counter: str, description: str) -> None:
    """Run a summary activity and count a failure instead of raising it.

    A failure leaves the issue without a summary, because nothing else writes one.
    """
    try:
        await workflow.execute_activity(
            activity,
            inputs,
            schedule_to_close_timeout=SUMMARY_SCHEDULE_TO_CLOSE_TIMEOUT,
            start_to_close_timeout=SUMMARY_START_TO_CLOSE_TIMEOUT,
            retry_policy=SUMMARY_RETRY_POLICY,
        )
    except ActivityError:
        workflow.logger.warning("Issue summary activity %s failed; the issue has no summary", activity)
        workflow.metric_meter().create_counter(fail_open_counter, description).add(1)
