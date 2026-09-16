import json
from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow

from products.error_tracking.backend.temporal.lifecycle.issue_reopened.types import (
    IssueReopenedSnapshot,
    IssueReopenedWorkflowInputs,
    IssueReopenedWorkflowResult,
)

WORKFLOW_NAME = "error-tracking-issue-reopened"

ACTIVITY_RETRY_POLICY = common.RetryPolicy(
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=15),
    maximum_attempts=10,
)
ACTIVITY_START_TO_CLOSE_TIMEOUT = timedelta(minutes=5)
ALERT_DISPATCH_PATCH = "error-tracking-alert-dispatch-activity"
# Unlimited attempts inside the window: the start is cheap and idempotent, and only a
# Temporal outage longer than this loses the alert.
ALERT_DISPATCH_RETRY_POLICY = common.RetryPolicy(
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(minutes=1),
    maximum_attempts=0,
)
ALERT_DISPATCH_SCHEDULE_TO_CLOSE_TIMEOUT = timedelta(hours=1)


@workflow.defn(name=WORKFLOW_NAME)
class ErrorTrackingIssueReopenedWorkflow(PostHogWorkflow):
    @staticmethod
    def workflow_id_for(notification_id: str) -> str:
        return f"{WORKFLOW_NAME}-{notification_id}"

    @staticmethod
    def parse_inputs(inputs: list[str]) -> IssueReopenedWorkflowInputs:
        if len(inputs) != 1:
            raise ValueError("Issue reopened workflow requires exactly one input")
        data = json.loads(inputs[0])
        data.pop("type", None)
        data.pop("event_properties", None)
        data["issue"] = IssueReopenedSnapshot(**data["issue"])
        return IssueReopenedWorkflowInputs(**data)

    @workflow.run
    async def run(self, inputs: IssueReopenedWorkflowInputs) -> IssueReopenedWorkflowResult:
        await workflow.execute_activity(
            "emit_issue_reopened_internal_event_activity",
            inputs,
            start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
            retry_policy=ACTIVITY_RETRY_POLICY,
        )
        await workflow.execute_activity(
            "emit_issue_reopened_signal_activity",
            inputs,
            start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
            retry_policy=ACTIVITY_RETRY_POLICY,
        )
        # Patched: executions in flight when this activity shipped replay the old sequence.
        if workflow.patched(ALERT_DISPATCH_PATCH):
            # Last, so a rejected start can never suppress the side effects above; its
            # own open-ended retry covers a Temporal outage. Starts are idempotent on the
            # notification id.
            await workflow.execute_activity(
                "dispatch_issue_reopened_alert_activity",
                inputs,
                schedule_to_close_timeout=ALERT_DISPATCH_SCHEDULE_TO_CLOSE_TIMEOUT,
                start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
                retry_policy=ALERT_DISPATCH_RETRY_POLICY,
            )
        return IssueReopenedWorkflowResult(notified=True)
