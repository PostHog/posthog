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
        return IssueReopenedWorkflowResult(notified=True)
