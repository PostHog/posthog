"""Temporal workflow for logs alert checking."""

import temporalio
from temporalio import workflow

from posthog.temporal.common.base import PostHogWorkflow

from products.logs.backend.temporal.activities import CheckAlertsInput, CheckAlertsOutput, check_alerts_activity
from products.logs.backend.temporal.constants import ACTIVITY_RETRY_POLICY, ACTIVITY_TIMEOUT, WORKFLOW_NAME


@temporalio.workflow.defn(name=WORKFLOW_NAME)
class LogsAlertCheckWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> CheckAlertsInput:
        return CheckAlertsInput()

    @temporalio.workflow.run
    async def run(self, input: CheckAlertsInput) -> CheckAlertsOutput:
        return await workflow.execute_activity(
            check_alerts_activity,
            input,
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=ACTIVITY_RETRY_POLICY,
        )
