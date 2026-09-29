from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.dataclasses import frozen

from products.growth.backend.temporal.account_audit.activities import (
    AccountAuditFinishInput,
    AccountAuditStartInput,
    TaskRunStatusInput,
    finish_account_audit_activity,
    get_account_audit_task_run_status_activity,
    start_account_audit_activity,
)

POLL_INTERVAL = timedelta(seconds=30)
MAX_POLL_ATTEMPTS = 360


@frozen
class AccountAuditWorkflowInput:
    organization_id: str
    team_id: int
    user_id: int


@workflow.defn(name="growth-account-audit")
class AccountAuditWorkflow:
    @staticmethod
    def workflow_id_for(organization_id: str) -> str:
        return f"growth-account-audit-{organization_id}"

    @workflow.run
    async def run(self, input: AccountAuditWorkflowInput) -> str:
        task_run_id = await workflow.execute_activity(
            start_account_audit_activity,
            AccountAuditStartInput(
                organization_id=input.organization_id,
                team_id=input.team_id,
                user_id=input.user_id,
                origin_key=f"{self.workflow_id_for(input.organization_id)}:{workflow.info().run_id}",
            ),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        for _ in range(MAX_POLL_ATTEMPTS):
            task_run = await workflow.execute_activity(
                get_account_audit_task_run_status_activity,
                TaskRunStatusInput(team_id=input.team_id, task_run_id=task_run_id),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            if task_run.terminal:
                if task_run.status != "completed" or not task_run.notebook_short_id:
                    raise RuntimeError("Account audit task did not produce a notebook")
                return await workflow.execute_activity(
                    finish_account_audit_activity,
                    AccountAuditFinishInput(
                        organization_id=input.organization_id,
                        team_id=input.team_id,
                        user_id=input.user_id,
                        task_run_id=task_run_id,
                        notebook_short_id=task_run.notebook_short_id,
                    ),
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            await workflow.sleep(POLL_INTERVAL)

        raise TimeoutError("Account audit task did not finish before the workflow deadline")


WORKFLOWS = [AccountAuditWorkflow]
