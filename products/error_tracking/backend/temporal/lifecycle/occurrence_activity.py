from temporalio import workflow
from temporalio.exceptions import ActivityError

from products.error_tracking.backend.temporal.lifecycle.policies import (
    ACTIVITY_RETRY_POLICY,
    ACTIVITY_START_TO_CLOSE_TIMEOUT,
)


async def record_occurrence_fail_open(activity: str, inputs: object) -> None:
    """Tell the alerts platform about the issue, and count a failure instead of raising it.

    A failure costs one appearance alert, which is never worth the issue's own alerts and events.
    """
    try:
        await workflow.execute_activity(
            activity,
            inputs,
            start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
            retry_policy=ACTIVITY_RETRY_POLICY,
        )
    except ActivityError:
        workflow.logger.warning("Issue occurrence activity %s failed; appearance alerts miss it", activity)
        workflow.metric_meter().create_counter(
            "error_tracking_issue_occurrence_fail_open", "Issue lifecycle workflows that did not record an occurrence"
        ).add(1)
