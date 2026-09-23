import datetime as dt

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from .activities import SyncOutcome, sync_access_rules_activity

WORKFLOW_NAME = "security-sync-access-rules"


@workflow.defn(name=WORKFLOW_NAME)
class SyncAccessRulesWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> None:
        return None

    @workflow.run
    async def run(self) -> SyncOutcome:
        return await workflow.execute_activity(
            sync_access_rules_activity,
            start_to_close_timeout=dt.timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=dt.timedelta(seconds=5)),
        )
