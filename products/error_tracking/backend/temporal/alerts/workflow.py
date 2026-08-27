from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow

from products.error_tracking.backend.temporal.alerts.types import (
    AlertDeliveryWorkflowInputs,
    AlertDeliveryWorkflowResult,
)

WORKFLOW_NAME = "error-tracking-alert-delivery"

ACTIVITY_RETRY_POLICY = common.RetryPolicy(
    initial_interval=timedelta(seconds=2),
    maximum_interval=timedelta(seconds=60),
    maximum_attempts=5,
)
ACTIVITY_START_TO_CLOSE_TIMEOUT = timedelta(minutes=5)


@workflow.defn(name=WORKFLOW_NAME)
class ErrorTrackingAlertDeliveryWorkflow(PostHogWorkflow):
    inputs_cls = AlertDeliveryWorkflowInputs

    @staticmethod
    def workflow_id_for(notification_id: str) -> str:
        # One workflow per lifecycle transition: redelivered starts are idempotent.
        return f"{WORKFLOW_NAME}-{notification_id}"

    @workflow.run
    async def run(self, inputs: AlertDeliveryWorkflowInputs) -> AlertDeliveryWorkflowResult:
        deliveries = await workflow.execute_activity(
            "deliver_alert_notifications_activity",
            inputs,
            start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
            retry_policy=ACTIVITY_RETRY_POLICY,
        )
        return AlertDeliveryWorkflowResult(deliveries=deliveries)
