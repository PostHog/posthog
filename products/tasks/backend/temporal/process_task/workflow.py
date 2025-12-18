import json
import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional

from django.conf import settings

import temporalio
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.workflow import ParentClosePolicy

from posthog.temporal.common.base import PostHogWorkflow

from products.tasks.backend.temporal.create_snapshot.workflow import CreateSnapshotForRepositoryInput

from .activities.cleanup_sandbox import CleanupSandboxInput, cleanup_sandbox
from .activities.execute_task_in_sandbox import ExecuteTaskInput, ExecuteTaskOutput, execute_task_in_sandbox
from .activities.get_sandbox_for_repository import (
    GetSandboxForRepositoryInput,
    GetSandboxForRepositoryOutput,
    get_sandbox_for_repository,
)
from .activities.get_task_processing_context import (
    GetTaskProcessingContextInput,
    TaskProcessingContext,
    get_task_processing_context,
)
from .activities.post_slack_update import PostSlackUpdateInput, post_slack_update
from .activities.track_workflow_event import TrackWorkflowEventInput, track_workflow_event
from .activities.update_task_run_status import UpdateTaskRunStatusInput, update_task_run_status


@dataclass
class ProcessTaskInput:
    run_id: str
    create_pr: bool = True
    slack_thread_context: Optional[dict[str, Any]] = None


@dataclass
class ProcessTaskOutput:
    success: bool
    task_result: Optional[ExecuteTaskOutput] = None
    error: Optional[str] = None
    sandbox_id: Optional[str] = None


@temporalio.workflow.defn(name="process-task")
class ProcessTaskWorkflow(PostHogWorkflow):
    def __init__(self) -> None:
        self._context: Optional[TaskProcessingContext] = None
        self._slack_thread_context: Optional[dict[str, Any]] = None

    @property
    def context(self) -> TaskProcessingContext:
        if self._context is None:
            raise RuntimeError("context accessed before being set")
        return self._context

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ProcessTaskInput:
        loaded = json.loads(inputs[0])
        return ProcessTaskInput(
            run_id=loaded["run_id"],
            create_pr=loaded.get("create_pr", True),
            slack_thread_context=loaded.get("slack_thread_context"),
        )

    @temporalio.workflow.run
    async def run(self, input: ProcessTaskInput) -> ProcessTaskOutput:
        sandbox_id = None
        run_id = input.run_id
        self._slack_thread_context = input.slack_thread_context

        try:
            self._context = await self._get_task_processing_context(input)
            await self._update_task_run_status("in_progress")

            await self._track_workflow_event(
                "process_task_workflow_started",
                {
                    "run_id": run_id,
                    "task_id": self.context.task_id,
                    "repository": self.context.repository,
                    "team_id": self.context.team_id,
                },
            )

            await self._post_slack_update()

            sandbox_output = await self._get_sandbox_for_repository()
            sandbox_id = sandbox_output.sandbox_id

            # TODO: Re-enable snapshot creation
            # if sandbox_output.should_create_snapshot:
            #     await self._trigger_snapshot_workflow()

            await self._post_slack_update()

            result = await self._execute_task_in_sandbox(sandbox_id)

            await self._track_workflow_event(
                "process_task_workflow_completed",
                {
                    "task_id": self.context.task_id,
                    "sandbox_id": sandbox_id,
                    "exit_code": result.exit_code,
                    "used_snapshot": sandbox_output.used_snapshot,
                },
            )

            await self._update_task_run_status("completed")
            await self._post_slack_update()

            return ProcessTaskOutput(
                success=True,
                task_result=result,
                error=None,
                sandbox_id=sandbox_id,
            )

        except asyncio.CancelledError:
            await self._update_task_run_status("cancelled")
            if sandbox_id:
                await self._cleanup_sandbox(sandbox_id)
                sandbox_id = None
            raise

        except Exception as e:
            error_message = str(e)[:500]
            if self._context:
                await self._track_workflow_event(
                    "process_task_workflow_failed",
                    {
                        "run_id": run_id,
                        "task_id": self.context.task_id,
                        "error_type": type(e).__name__,
                        "error_message": error_message,
                        "sandbox_id": sandbox_id,
                    },
                )
                await self._update_task_run_status("failed", error_message=error_message)
                await self._post_slack_update()

            return ProcessTaskOutput(
                success=False,
                task_result=None,
                error=str(e),
                sandbox_id=sandbox_id,
            )

        finally:
            if sandbox_id:
                await self._cleanup_sandbox(sandbox_id)

    async def _get_task_processing_context(self, input: ProcessTaskInput) -> TaskProcessingContext:
        return await workflow.execute_activity(
            get_task_processing_context,
            GetTaskProcessingContextInput(run_id=input.run_id, create_pr=input.create_pr),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _get_sandbox_for_repository(self) -> GetSandboxForRepositoryOutput:
        return await workflow.execute_activity(
            get_sandbox_for_repository,
            GetSandboxForRepositoryInput(context=self.context),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _cleanup_sandbox(self, sandbox_id: str) -> None:
        cleanup_input = CleanupSandboxInput(sandbox_id=sandbox_id)
        await workflow.execute_activity(
            cleanup_sandbox,
            cleanup_input,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _execute_task_in_sandbox(self, sandbox_id: str) -> ExecuteTaskOutput:
        execute_input = ExecuteTaskInput(context=self.context, sandbox_id=sandbox_id)
        return await workflow.execute_activity(
            execute_task_in_sandbox,
            execute_input,
            start_to_close_timeout=timedelta(minutes=60),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _track_workflow_event(self, event_name: str, properties: dict) -> None:
        track_input = TrackWorkflowEventInput(
            event_name=event_name,
            distinct_id=self.context.distinct_id,
            properties=properties,
        )
        await workflow.execute_activity(
            track_workflow_event,
            track_input,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

    async def _update_task_run_status(self, status: str, error_message: Optional[str] = None) -> None:
        await workflow.execute_activity(
            update_task_run_status,
            UpdateTaskRunStatusInput(
                run_id=self.context.run_id,
                status=status,
                error_message=error_message,
            ),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _trigger_snapshot_workflow(self) -> None:
        workflow_id = (
            f"create-snapshot-for-repository-{self.context.github_integration_id}-"
            f"{self.context.repository.replace('/', '-')}"
        )

        await workflow.start_child_workflow(
            workflow="create-snapshot-for-repository",
            arg=CreateSnapshotForRepositoryInput(
                github_integration_id=self.context.github_integration_id,
                repository=self.context.repository,
                team_id=self.context.team_id,
            ),
            id=workflow_id,
            task_queue=settings.TASKS_TASK_QUEUE,
            parent_close_policy=ParentClosePolicy.ABANDON,  # This will allow the snapshot workflow to continue even if the task workflow fails or closes
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

    async def _post_slack_update(self) -> None:
        if not self._slack_thread_context:
            return
        await workflow.execute_activity(
            post_slack_update,
            PostSlackUpdateInput(
                run_id=self.context.run_id,
                slack_thread_context=self._slack_thread_context,
            ),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
