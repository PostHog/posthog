from datetime import timedelta

from temporalio import common, workflow
from temporalio.exceptions import ActivityError, ApplicationError

from posthog.temporal.common.base import PostHogWorkflow

from products.error_tracking.backend.temporal.alerts.types import (
    THREAD_BUSY_ERROR_TYPE,
    AlertDeliveryWorkflowInputs,
    AlertDeliveryWorkflowResult,
)

WORKFLOW_NAME = "error-tracking-alert-delivery"

ACTIVITY_RETRY_POLICY = common.RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=60),
    maximum_attempts=10,
)
ACTIVITY_START_TO_CLOSE_TIMEOUT = timedelta(minutes=5)
# A thread's send claim is held by one notification at a time. Contention is not a
# fault, so it is waited out here instead of spending the activity's retry budget.
# The wait must outlast the claim TTL (delivery.py): a holder that died between
# posting and saving frees the thread only when its claim goes stale.
BUSY_RETRY_DELAY = timedelta(seconds=5)
BUSY_WAIT_LIMIT = timedelta(minutes=10)


@workflow.defn(name=WORKFLOW_NAME)
class ErrorTrackingAlertDeliveryWorkflow(PostHogWorkflow):
    inputs_cls = AlertDeliveryWorkflowInputs

    @staticmethod
    def workflow_id_for(notification_id: str) -> str:
        # One workflow per lifecycle transition: redelivered starts are idempotent.
        return f"{WORKFLOW_NAME}-{notification_id}"

    @workflow.run
    async def run(self, inputs: AlertDeliveryWorkflowInputs) -> AlertDeliveryWorkflowResult:
        deadline = workflow.now() + BUSY_WAIT_LIMIT
        while True:
            try:
                deliveries = await workflow.execute_activity(
                    "deliver_alert_notifications_activity",
                    inputs,
                    start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
                    retry_policy=ACTIVITY_RETRY_POLICY,
                )
            except ActivityError as error:
                if not _is_thread_busy(error) or workflow.now() >= deadline:
                    raise
                await workflow.sleep(BUSY_RETRY_DELAY)
                continue
            return AlertDeliveryWorkflowResult(deliveries=deliveries)


def _is_thread_busy(error: ActivityError) -> bool:
    return isinstance(error.cause, ApplicationError) and error.cause.type == THREAD_BUSY_ERROR_TYPE
