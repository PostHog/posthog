import json
from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from products.error_tracking.backend.temporal.change_dispatch.activities import dispatch_issue_changes_activity
    from products.error_tracking.backend.temporal.change_dispatch.types import (
        ChangeDispatchInputs,
        ChangeDispatchResult,
    )

WORKFLOW_NAME = "error-tracking-issue-change-dispatch"

# No retry: undispatched rows stay in the outbox and the next scheduled run picks them up.
ACTIVITY_RETRY_POLICY = common.RetryPolicy(maximum_attempts=1)
ACTIVITY_START_TO_CLOSE_TIMEOUT = timedelta(minutes=2)


@workflow.defn(name=WORKFLOW_NAME)
class ErrorTrackingIssueChangeDispatchWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> ChangeDispatchInputs:
        if inputs:
            return ChangeDispatchInputs(**json.loads(inputs[0]))
        return ChangeDispatchInputs()

    @workflow.run
    async def run(self, inputs: ChangeDispatchInputs | None = None) -> ChangeDispatchResult:
        return await workflow.execute_activity(
            dispatch_issue_changes_activity,
            inputs or ChangeDispatchInputs(),
            start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
            retry_policy=ACTIVITY_RETRY_POLICY,
        )
