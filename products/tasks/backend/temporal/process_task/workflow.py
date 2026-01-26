import json
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal, Optional

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
from .activities.start_agent_server import StartAgentServerInput, StartAgentServerOutput, start_agent_server
from .activities.track_workflow_event import TrackWorkflowEventInput, track_workflow_event
from .activities.update_task_run_status import UpdateTaskRunStatusInput, update_task_run_status

INACTIVITY_TIMEOUT_MINUTES = 5


@dataclass
class ProcessTaskInput:
    run_id: str
    create_pr: bool = True
    slack_thread_context: Optional[dict[str, Any]] = None
    execution_mode: Literal["batch", "cloud"] = "batch"
    initial_prompt: Optional[str] = None


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
        self._should_close = False
        self._last_activity_time: datetime = datetime.min
        self._sandbox_id: Optional[str] = None

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
            execution_mode=loaded.get("execution_mode", "batch"),
            initial_prompt=loaded.get("initial_prompt"),
        )

    @temporalio.workflow.signal
    def close(self) -> None:
        """Signal to close the session and clean up."""
        self._should_close = True

    @temporalio.workflow.signal
    def heartbeat(self) -> None:
        """Signal to keep the session alive."""
        self._last_activity_time = workflow.now()

    @temporalio.workflow.run
    async def run(self, input: ProcessTaskInput) -> ProcessTaskOutput:
        self._sandbox_id = None
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
                    "execution_mode": input.execution_mode,
                },
            )

            await self._post_slack_update()

            sandbox_output = await self._get_sandbox_for_repository()
            self._sandbox_id = sandbox_output.sandbox_id

            await self._post_slack_update()

            if input.execution_mode == "cloud":
                return await self._run_cloud_lifecycle(input, sandbox_output)
            else:
                return await self._run_batch_execution(sandbox_output)

        except asyncio.CancelledError:
            await self._update_task_run_status("cancelled")
            if self._sandbox_id:
                await self._cleanup_sandbox(self._sandbox_id)
                self._sandbox_id = None
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
                        "sandbox_id": self._sandbox_id,
                    },
                )
                await self._update_task_run_status("failed", error_message=error_message)
                await self._post_slack_update()

            return ProcessTaskOutput(
                success=False,
                task_result=None,
                error=str(e),
                sandbox_id=self._sandbox_id,
            )

        finally:
            if self._sandbox_id:
                await self._cleanup_sandbox(self._sandbox_id)

    async def _run_batch_execution(self, sandbox_output: GetSandboxForRepositoryOutput) -> ProcessTaskOutput:
        """Original batch execution mode - runs task to completion."""
        sandbox_id = self._sandbox_id
        assert sandbox_id is not None

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

    async def _run_cloud_lifecycle(
        self, input: ProcessTaskInput, sandbox_output: GetSandboxForRepositoryOutput
    ) -> ProcessTaskOutput:
        """
        Cloud execution mode - starts agent server and waits for close signal or timeout.

        The agent server connects back to PostHog API via SSE for bidirectional communication.
        Workflow completes on idle timeout, and can be restarted to resume from logs.
        """
        sandbox_id = self._sandbox_id
        assert sandbox_id is not None

        agent_result = await self._start_agent_server(sandbox_id, input.initial_prompt)

        if not agent_result.success:
            await self._update_task_run_status("failed", agent_result.error)
            return ProcessTaskOutput(
                success=False,
                error=agent_result.error,
                sandbox_id=sandbox_id,
            )

        self._last_activity_time = workflow.now()
        await self._wait_for_close_or_timeout()

        await self._track_workflow_event(
            "process_task_workflow_completed",
            {
                "task_id": self.context.task_id,
                "sandbox_id": sandbox_id,
                "execution_mode": "cloud",
                "used_snapshot": sandbox_output.used_snapshot,
            },
        )

        await self._update_task_run_status("completed")
        return ProcessTaskOutput(success=True, sandbox_id=sandbox_id)

    async def _wait_for_close_or_timeout(self) -> None:
        """Wait until close signal or inactivity timeout."""
        timeout = timedelta(minutes=INACTIVITY_TIMEOUT_MINUTES)

        while not self._should_close:
            now = workflow.now()
            time_since_activity = now - self._last_activity_time
            remaining = timeout - time_since_activity

            if remaining <= timedelta(0):
                workflow.logger.info("Session timed out due to inactivity")
                break

            try:
                await workflow.wait_condition(
                    lambda: self._should_close,
                    timeout=remaining,
                )
            except TimeoutError:
                pass

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

    async def _start_agent_server(
        self, sandbox_id: str, initial_prompt: Optional[str] = None
    ) -> StartAgentServerOutput:
        return await workflow.execute_activity(
            start_agent_server,
            StartAgentServerInput(
                context=self.context,
                sandbox_id=sandbox_id,
                initial_prompt=initial_prompt,
            ),
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=1),
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
            parent_close_policy=ParentClosePolicy.ABANDON,
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
