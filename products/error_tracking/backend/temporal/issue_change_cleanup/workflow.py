import json
from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from products.error_tracking.backend.temporal.issue_change_cleanup.activities import cleanup_issue_changes_activity
    from products.error_tracking.backend.temporal.issue_change_cleanup.types import (
        IssueChangeCleanupInputs,
        IssueChangeCleanupResult,
    )

WORKFLOW_NAME = "error-tracking-issue-change-cleanup"

# One attempt: a run that fails leaves the rest for tomorrow's run, which reads the same cutoff rule.
ACTIVITY_RETRY_POLICY = common.RetryPolicy(maximum_attempts=1)
ACTIVITY_START_TO_CLOSE_TIMEOUT = timedelta(hours=2)
# Each batch heartbeats, so a worker that died mid-run frees the activity quickly.
ACTIVITY_HEARTBEAT_TIMEOUT = timedelta(minutes=5)


@workflow.defn(name=WORKFLOW_NAME)
class ErrorTrackingIssueChangeCleanupWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> IssueChangeCleanupInputs:
        if inputs:
            data = json.loads(inputs[0])
            return IssueChangeCleanupInputs(**data)
        return IssueChangeCleanupInputs()

    @workflow.run
    async def run(self, inputs: IssueChangeCleanupInputs | None = None) -> IssueChangeCleanupResult:
        if inputs is None:
            inputs = IssueChangeCleanupInputs()

        return await workflow.execute_activity(
            cleanup_issue_changes_activity,
            inputs,
            start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
            heartbeat_timeout=ACTIVITY_HEARTBEAT_TIMEOUT,
            retry_policy=ACTIVITY_RETRY_POLICY,
        )
