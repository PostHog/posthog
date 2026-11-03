import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest

from temporalio import activity, workflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.tasks.backend.github_recovery import GitHubRecoveryCheck
from products.tasks.backend.temporal.process_task.activities.update_task_run_status import UpdateTaskRunStatusInput
from products.tasks.backend.temporal.process_task.workflow import ProcessTaskWorkflow


@workflow.defn
class GitHubRecoveryTestWorkflow:
    def __init__(self) -> None:
        self.process = ProcessTaskWorkflow()

    @workflow.signal
    def github_access_restored(self) -> None:
        self.process.github_access_restored()

    @workflow.run
    async def run(self, run_id: str) -> bool:
        return await self.process._wait_for_github_readiness(run_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["resume", "expire", "during_check", "transient"])
async def test_recovery_waits_for_access_event_or_original_deadline(case: str) -> None:
    checked = asyncio.Event()
    release_check = asyncio.Event()
    check_count = 0
    updates: list[UpdateTaskRunStatusInput] = []
    restored = False

    async with await WorkflowEnvironment.start_time_skipping() as env:
        deadline = await env.get_current_time() + timedelta(days=7)

        @activity.defn(name="check_self_driving_github_readiness")
        async def check_access(run_id: str) -> GitHubRecoveryCheck:
            nonlocal check_count
            check_count += 1
            checked.set()
            if case == "during_check" and check_count == 1:
                await release_check.wait()
                return GitHubRecoveryCheck(status="suspended", retry_until=deadline)
            return GitHubRecoveryCheck(
                status="ready" if restored else "retry" if case == "transient" else "suspended",
                retry_until=deadline,
            )

        @activity.defn(name="update_task_run_status")
        async def update_status(input: UpdateTaskRunStatusInput) -> None:
            updates.append(input)

        async with Worker(
            env.client,
            task_queue="github-recovery-test",
            workflows=[GitHubRecoveryTestWorkflow],
            activities=[check_access, update_status],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await env.client.start_workflow(
                GitHubRecoveryTestWorkflow.run,
                "example-run",
                id=str(uuid4()),
                task_queue="github-recovery-test",
            )
            await asyncio.wait_for(checked.wait(), timeout=20)
            if case == "during_check":
                restored = True
                await handle.signal(GitHubRecoveryTestWorkflow.github_access_restored)
                release_check.set()
            elif case == "expire":
                assert await handle.result() is False
                assert check_count == 1
                assert len(updates) == 1
                assert updates[0].status == "cancelled"
                assert "seven days" in (updates[0].error_message or "")
                return
            else:
                await env.sleep(timedelta(minutes=20))
                assert check_count == (6 if case == "transient" else 1)
                await env.sleep(timedelta(minutes=20))
                assert check_count == (6 if case == "transient" else 1)
                restored = True
                await handle.signal(GitHubRecoveryTestWorkflow.github_access_restored)
            assert await handle.result() is True
            assert check_count == (7 if case == "transient" else 2)
            assert updates == []
