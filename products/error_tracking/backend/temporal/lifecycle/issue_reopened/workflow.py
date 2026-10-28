import json
import asyncio

from temporalio import workflow

from posthog.temporal.common.base import PostHogWorkflow

from products.error_tracking.backend.temporal.lifecycle.issue_reopened.types import (
    IssueReopenedSnapshot,
    IssueReopenedWorkflowInputs,
    IssueReopenedWorkflowResult,
)
from products.error_tracking.backend.temporal.lifecycle.policies import (
    ACTIVITY_RETRY_POLICY,
    ACTIVITY_START_TO_CLOSE_TIMEOUT,
    ALERT_DISPATCH_PATCH,
    ALERT_DISPATCH_RETRY_POLICY,
    ALERT_DISPATCH_SCHEDULE_TO_CLOSE_TIMEOUT,
)
from products.error_tracking.backend.temporal.lifecycle.summary_activity import execute_summary_activity

WORKFLOW_NAME = "error-tracking-issue-reopened"
SUMMARY_ON_REOPEN_PATCH = "error-tracking-summary-on-reopen-activity"


async def run_issue_reopened_side_effects(inputs: IssueReopenedWorkflowInputs) -> None:
    """Alert, internal event and signal for a reopened issue.

    Shared with the issue-created workflow, which reaches this state when auto-merge moves a
    new fingerprint onto a dormant issue.
    """
    # Patched: executions in flight when this activity shipped replay the old sequence.
    # Dispatch runs alongside the other side effects and is always awaited, so a
    # failure on either side never suppresses the other. Its open-ended retry covers
    # a Temporal outage; starts are idempotent on the notification id.
    dispatch = (
        asyncio.create_task(
            workflow.execute_activity(
                "dispatch_issue_reopened_alert_activity",
                inputs,
                schedule_to_close_timeout=ALERT_DISPATCH_SCHEDULE_TO_CLOSE_TIMEOUT,
                start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
                retry_policy=ALERT_DISPATCH_RETRY_POLICY,
            )
        )
        if workflow.patched(ALERT_DISPATCH_PATCH)
        else None
    )
    # Patched for the same reason. The alert and the emit activities do not wait for the summary.
    # The workflow awaits it before it completes, because a task left unawaited is dropped when the workflow returns.
    summary = (
        asyncio.create_task(
            execute_summary_activity(
                "generate_issue_reopened_summary_activity",
                inputs,
                fail_open_counter="error_tracking_issue_reopened_summary_fail_open",
                description="Issue-reopened side effects whose summary activity failed",
            )
        )
        if workflow.patched(SUMMARY_ON_REOPEN_PATCH)
        else None
    )
    try:
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
    finally:
        if dispatch is not None:
            await dispatch
        if summary is not None:
            await summary


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
        await run_issue_reopened_side_effects(inputs)
        return IssueReopenedWorkflowResult(notified=True)
