from datetime import timedelta

from temporalio import common, workflow
from temporalio.exceptions import ActivityError

# One write, so a short deadline is plenty. It runs beside the issue's own alerts and events, and a
# stalled registry must not hold the workflow open for long.
OCCURRENCE_START_TO_CLOSE_TIMEOUT = timedelta(seconds=30)
OCCURRENCE_SCHEDULE_TO_CLOSE_TIMEOUT = timedelta(minutes=2)
OCCURRENCE_RETRY_POLICY = common.RetryPolicy(maximum_attempts=3)


async def record_occurrence_fail_open(activity: str, inputs: object) -> None:
    """Tell the alerts platform about the issue, and count a failure instead of raising it.

    A failure costs one appearance alert, which is never worth the issue's own alerts and events.
    """
    try:
        await workflow.execute_activity(
            activity,
            inputs,
            start_to_close_timeout=OCCURRENCE_START_TO_CLOSE_TIMEOUT,
            schedule_to_close_timeout=OCCURRENCE_SCHEDULE_TO_CLOSE_TIMEOUT,
            retry_policy=OCCURRENCE_RETRY_POLICY,
        )
    except ActivityError:
        workflow.logger.warning("Issue occurrence activity %s failed; appearance alerts miss it", activity)
        workflow.metric_meter().create_counter(
            "error_tracking_issue_occurrence_fail_open", "Issue lifecycle workflows that did not record an occurrence"
        ).add(1)
