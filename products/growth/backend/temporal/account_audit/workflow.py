import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.dataclasses import frozen

from products.growth.backend.temporal.account_audit.activities import (
    AccountAuditFinishInput,
    AccountAuditStartInput,
    TaskRunStatusInput,
    cancel_account_audit_task_activity,
    finish_account_audit_activity,
    get_account_audit_task_run_status_activity,
    start_account_audit_activity,
)

POLL_INTERVAL = timedelta(seconds=30)
TASK_TIMEOUT = timedelta(hours=3)
COST_SETTLE_TIMEOUT = timedelta(minutes=3)
WORKFLOW_TIMEOUT = TASK_TIMEOUT + timedelta(minutes=30)


@frozen
class AccountAuditWorkflowInput:
    organization_id: str
    team_id: int
    user_id: int
    reason: str = ""
    skill_name: str = "onboarding-account-audit"


@workflow.defn(name="growth-account-audit")
class AccountAuditWorkflow:
    @staticmethod
    def workflow_id_for(organization_id: str) -> str:
        return f"growth-account-audit-{organization_id}"

    @workflow.run
    async def run(self, input: AccountAuditWorkflowInput) -> str:
        start_input = AccountAuditStartInput(
            organization_id=input.organization_id,
            team_id=input.team_id,
            user_id=input.user_id,
            reason=input.reason,
            skill_name=input.skill_name,
            origin_key=f"{self.workflow_id_for(input.organization_id)}:{workflow.info().run_id}",
        )
        try:
            return await self._audit(input, start_input)
        except (Exception, asyncio.CancelledError):
            await workflow.execute_activity(
                cancel_account_audit_task_activity,
                start_input,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            raise

    async def _audit(self, input: AccountAuditWorkflowInput, start_input: AccountAuditStartInput) -> str:
        deadline = workflow.now() + TASK_TIMEOUT
        task_run_id = await workflow.execute_activity(
            start_account_audit_activity,
            start_input,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        cost_deadline = None
        while workflow.now() < deadline:
            task_run = await workflow.execute_activity(
                get_account_audit_task_run_status_activity,
                TaskRunStatusInput(team_id=input.team_id, task_run_id=task_run_id),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            if task_run.terminal:
                if task_run.status != "completed" or not task_run.notebook_short_id:
                    raise ApplicationError(
                        f"Account audit task ended with status {task_run.status} without a verified notebook",
                        type="AccountAuditTaskFailed",
                        non_retryable=True,
                    )
                if cost_deadline is None:
                    cost_deadline = workflow.now() + COST_SETTLE_TIMEOUT
                    deadline = max(deadline, cost_deadline)
                if not task_run.cost_pending or workflow.now() >= cost_deadline:
                    return await workflow.execute_activity(
                        finish_account_audit_activity,
                        AccountAuditFinishInput(
                            organization_id=input.organization_id,
                            team_id=input.team_id,
                            user_id=input.user_id,
                            task_run_id=task_run_id,
                            notebook_short_id=task_run.notebook_short_id,
                            reason=input.reason,
                            skill_name=input.skill_name,
                        ),
                        start_to_close_timeout=timedelta(minutes=1),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )
            await workflow.sleep(POLL_INTERVAL)
        raise ApplicationError(
            "Account audit task exceeded its deadline", type="AccountAuditTimedOut", non_retryable=True
        )


WORKFLOWS = [AccountAuditWorkflow]
