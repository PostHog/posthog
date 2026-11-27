from datetime import timedelta
from uuid import uuid4

import pytest

from temporalio import activity, workflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker

from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import (
    GetTaskProcessingContextInput,
    TaskProcessingContext,
)
from products.tasks.backend.temporal.process_task.workflow import ProcessTaskInput, ProcessTaskWorkflow


@workflow.defn(name="git-egress-history")
class LegacyGitHistory:
    @workflow.run
    async def run(self, run_id: str) -> str:
        await workflow.execute_activity(
            "get_task_processing_context",
            GetTaskProcessingContextInput(run_id=run_id, launches_agent=True),
            start_to_close_timeout=timedelta(minutes=2),
        )
        return await workflow.execute_activity(
            "record_git_path", "legacy", start_to_close_timeout=timedelta(seconds=10)
        )


@workflow.defn(name="git-egress-history")
class CurrentGitHistory:
    @workflow.run
    async def run(self, run_id: str) -> str:
        task = ProcessTaskWorkflow()
        task._context = await task._get_task_processing_context(ProcessTaskInput(run_id=run_id))
        if task._git_egress_required():
            await workflow.execute_activity("git_route_ready", start_to_close_timeout=timedelta(seconds=10))
        return await workflow.execute_activity(
            "record_git_path",
            "brokered" if task._git_egress_required() else "legacy",
            start_to_close_timeout=timedelta(seconds=10),
        )


@pytest.mark.asyncio
async def test_old_history_ignores_new_activity_data_and_new_workflow_negotiates_routing() -> None:
    support: list[bool] = []
    ready: list[bool] = []

    @activity.defn(name="get_task_processing_context")
    async def context(input: GetTaskProcessingContextInput) -> TaskProcessingContext:
        support.append(input.supports_agent_egress_git_reads)
        return TaskProcessingContext(
            task_id="synthetic-task",
            run_id=input.run_id,
            team_id=1,
            team_uuid="synthetic-team",
            organization_id="synthetic-org",
            github_integration_id=None,
            repository="example/repo",
            distinct_id="synthetic-actor",
            agent_egress_git_reads=True,
        )

    @activity.defn(name="git_route_ready")
    async def route_ready() -> None:
        ready.append(True)

    @activity.defn(name="record_git_path")
    async def record_path(path: str) -> str:
        return path

    queue = f"git-egress-replay-{uuid4()}"
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue=queue,
            workflows=[LegacyGitHistory],
            activities=[context, route_ready, record_path],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await environment.client.start_workflow(
                LegacyGitHistory.run,
                str(uuid4()),
                id=str(uuid4()),
                task_queue=queue,
                execution_timeout=timedelta(minutes=1),
            )
            assert await handle.result() == "legacy"
            history = await handle.fetch_history()
        await Replayer(workflows=[CurrentGitHistory], workflow_runner=UnsandboxedWorkflowRunner()).replay_workflow(
            history
        )
        async with Worker(
            environment.client,
            task_queue=queue,
            workflows=[CurrentGitHistory],
            activities=[context, route_ready, record_path],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            assert (
                await environment.client.execute_workflow(
                    CurrentGitHistory.run,
                    str(uuid4()),
                    id=str(uuid4()),
                    task_queue=queue,
                    execution_timeout=timedelta(minutes=1),
                )
                == "brokered"
            )
    assert support == [False, True]
    assert ready == [True]
