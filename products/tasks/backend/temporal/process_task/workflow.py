import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

import temporalio
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger

from .activities.check_snapshot_exists_for_repository import (
    CheckSnapshotExistsForRepositoryInput,
    check_snapshot_exists_for_repository,
)
from .activities.cleanup_personal_api_key import cleanup_personal_api_key
from .activities.cleanup_sandbox import CleanupSandboxInput, cleanup_sandbox
from .activities.clone_repository import CloneRepositoryInput, clone_repository
from .activities.create_sandbox_from_snapshot import (
    CreateSandboxFromSnapshotInput,
    CreateSandboxFromSnapshotOutput,
    create_sandbox_from_snapshot,
)
from .activities.create_snapshot import CreateSnapshotInput, create_snapshot
from .activities.execute_task_in_sandbox import ExecuteTaskInput, ExecuteTaskOutput, execute_task_in_sandbox
from .activities.get_sandbox_for_setup import GetSandboxForSetupInput, GetSandboxForSetupOutput, get_sandbox_for_setup
from .activities.get_task_processing_context import TaskProcessingContext, get_task_processing_context
from .activities.setup_repository import SetupRepositoryInput, setup_repository
from .activities.track_workflow_event import TrackWorkflowEventInput, track_workflow_event

logger = get_logger(__name__)


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

    @property
    def context(self) -> TaskProcessingContext:
        if self._context is None:
            raise RuntimeError("context accessed before being set")
        return self._context

    @staticmethod
    def parse_inputs(inputs: list[str]) -> str:
        loaded = json.loads(inputs[0])
        return loaded["run_id"]

    @temporalio.workflow.run
    async def run(self, run_id: str) -> ProcessTaskOutput:
        sandbox_id = None
        personal_api_key_id = None

        try:
            self._context = await self._get_task_processing_context(run_id)

            await self._track_workflow_event(
                "process_task_workflow_started",
                {
                    "run_id": run_id,
                    "task_id": self.context.task_id,
                    "repository": self.context.repository,
                    "team_id": self.context.team_id,
                },
            )

            snapshot_id = await self._get_snapshot_for_repository()

            create_sandbox_output = await self._create_sandbox_from_snapshot(snapshot_id)

            sandbox_id = create_sandbox_output.sandbox_id
            personal_api_key_id = create_sandbox_output.personal_api_key_id

            result = await self._execute_task_in_sandbox(sandbox_id)

            await self._track_workflow_event(
                "process_task_workflow_completed",
                {
                    "task_id": self.context.task_id,
                    "sandbox_id": sandbox_id,
                    "exit_code": result.exit_code,
                },
            )

            return ProcessTaskOutput(
                success=True,
                task_result=result,
                error=None,
                sandbox_id=sandbox_id,
            )

        except Exception as e:
            if self._context:
                await self._track_workflow_event(
                    "process_task_workflow_failed",
                    {
                        "run_id": run_id,
                        "task_id": self.context.task_id,
                        "error_type": type(e).__name__,
                        "error_message": str(e)[:500],
                        "sandbox_id": sandbox_id,
                    },
                )

            return ProcessTaskOutput(
                success=False,
                task_result=None,
                error=str(e),
                sandbox_id=sandbox_id,
            )

        finally:
            if personal_api_key_id:
                await self._cleanup_personal_api_key(personal_api_key_id)
            if sandbox_id:
                await self._cleanup_sandbox(sandbox_id)

    async def _get_task_processing_context(self, run_id: str) -> TaskProcessingContext:
        return await workflow.execute_activity(
            get_task_processing_context,
            run_id,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _get_snapshot_for_repository(self) -> str:
        check_input = CheckSnapshotExistsForRepositoryInput(context=self.context)

        check_result = await workflow.execute_activity(
            check_snapshot_exists_for_repository,
            check_input,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        if check_result.snapshot_id:
            return check_result.snapshot_id

        return await self._setup_snapshot_with_repository()

    async def _get_sandbox_for_setup(self) -> GetSandboxForSetupOutput:
        get_sandbox_input = GetSandboxForSetupInput(context=self.context)
        return await workflow.execute_activity(
            get_sandbox_for_setup,
            get_sandbox_input,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _clone_repository_in_sandbox(self, sandbox_id: str) -> None:
        clone_input = CloneRepositoryInput(context=self.context, sandbox_id=sandbox_id)
        await workflow.execute_activity(
            clone_repository,
            clone_input,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _setup_repository_in_sandbox(self, sandbox_id: str) -> None:
        setup_repo_input = SetupRepositoryInput(context=self.context, sandbox_id=sandbox_id)
        await workflow.execute_activity(
            setup_repository,
            setup_repo_input,
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

    async def _snapshot_sandbox(self, sandbox_id: str) -> str:
        snapshot_input = CreateSnapshotInput(context=self.context, sandbox_id=sandbox_id)
        return await workflow.execute_activity(
            create_snapshot,
            snapshot_input,
            start_to_close_timeout=timedelta(minutes=20),
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

    async def _setup_snapshot_with_repository(self, setup_repository: bool = True) -> str:
        setup_sandbox_id = None
        setup_personal_api_key_id = None

        try:
            setup_output = await self._get_sandbox_for_setup()
            setup_sandbox_id = setup_output.sandbox_id
            setup_personal_api_key_id = setup_output.personal_api_key_id
            setup_failed = False

            await self._clone_repository_in_sandbox(setup_sandbox_id)

            if setup_repository:
                try:
                    await self._setup_repository_in_sandbox(setup_sandbox_id)
                except Exception as e:
                    logger.warning(
                        f"Repository setup failed for {self.context.repository}: {e}. "
                        f"Will create snapshot without setup. Tasks will need to handle setup themselves."
                    )
                    await self._track_workflow_event(
                        "repository_setup_failed_using_base_snapshot",
                        {
                            "task_id": self.context.task_id,
                            "repository": self.context.repository,
                            "error": str(e)[:500],
                        },
                    )

                    setup_failed = True

            snapshot_id = await self._snapshot_sandbox(setup_sandbox_id)

        finally:
            if setup_personal_api_key_id:
                await self._cleanup_personal_api_key(setup_personal_api_key_id)
            if setup_sandbox_id:
                await self._cleanup_sandbox(setup_sandbox_id)

        if setup_failed:
            return await self._setup_snapshot_with_repository(setup_repository=False)
        else:
            return snapshot_id

    async def _create_sandbox_from_snapshot(self, snapshot_id: str) -> CreateSandboxFromSnapshotOutput:
        create_sandbox_input = CreateSandboxFromSnapshotInput(context=self.context, snapshot_id=snapshot_id)
        return await workflow.execute_activity(
            create_sandbox_from_snapshot,
            create_sandbox_input,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _cleanup_personal_api_key(self, personal_api_key_id: str) -> None:
        try:
            await workflow.execute_activity(
                cleanup_personal_api_key,
                personal_api_key_id,
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except Exception as e:
            logger.warning(f"Failed to cleanup personal API key {personal_api_key_id}: {e}")

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
