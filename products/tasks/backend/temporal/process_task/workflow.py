import json
from datetime import timedelta

import temporalio
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger

from .activities import (
    check_snapshot_exists_for_repository,
    cleanup_sandbox,
    clone_repository,
    create_sandbox_from_snapshot,
    create_snapshot,
    execute_task_in_sandbox,
    get_sandbox_for_setup,
    get_task_details,
    setup_repository,
)
from .schemas import (
    CheckSnapshotExistsForRepositoryInput,
    CleanupSandboxInput,
    CloneRepositoryInput,
    CreateSandboxFromSnapshotInput,
    CreateSnapshotInput,
    ExecuteTaskInput,
    GetSandboxForSetupInput,
    SetupRepositoryInput,
    TaskDetails,
)

logger = get_logger(__name__)


@temporalio.workflow.defn(name="process-task")
class ProcessTaskWorkflow(PostHogWorkflow):
    """Main workflow for processing tasks"""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> str:
        loaded = json.loads(inputs[0])
        return loaded["task_id"]

    @temporalio.workflow.run
    async def run(self, task_id: str) -> dict:
        sandbox_id = None

        try:
            task_details = await self._get_task_details(task_id)

            # Get snapshot for repository
            logger.info(f"Getting snapshot for repository {task_details.repository}")

            snapshot_id = await self._get_snapshot_for_repository(
                task_details.github_integration_id,
                task_details.team_id,
                task_details.repository,
            )

            # Create sandbox from snapshot
            sandbox_id = await self._create_sandbox_from_snapshot(snapshot_id)

            # Execute task
            await self._execute_task_in_sandbox(sandbox_id, task_id, task_details.repository)

            return {
                "success": True,
            }

        except Exception as e:
            logger.exception(f"Agent workflow failed: {e}")
            return {
                "success": False,
                "error": str(e),
            }

        finally:
            if sandbox_id:
                try:
                    cleanup_input = CleanupSandboxInput(sandbox_id=sandbox_id)
                    await workflow.execute_activity(
                        cleanup_sandbox,
                        cleanup_input,
                        start_to_close_timeout=timedelta(minutes=5),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )
                except Exception:
                    logger.warning(f"Failed to cleanup sandbox {sandbox_id}")

    async def _get_task_details(self, task_id: str) -> TaskDetails:
        logger.info(f"Getting task details for task {task_id}")
        return await workflow.execute_activity(
            get_task_details,
            task_id,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _get_snapshot_for_repository(self, github_integration_id: int, team_id: int, repository: str) -> str:
        check_input = CheckSnapshotExistsForRepositoryInput(
            github_integration_id=github_integration_id,
            repository=repository,
        )

        check_result = await workflow.execute_activity(
            check_snapshot_exists_for_repository,
            check_input,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        if check_result.snapshot_id:
            return check_result.snapshot_id

        return await self._setup_snapshot_with_repository(github_integration_id, team_id, repository)

    async def _setup_snapshot_with_repository(
        self,
        github_integration_id: int,
        team_id: int,
        repository: str,
    ) -> str:
        sandbox_id = None

        try:
            # Get sandbox for setup (finds existing snapshot or uses default template)
            get_sandbox_input = GetSandboxForSetupInput(
                github_integration_id=github_integration_id,
                team_id=team_id,
            )
            sandbox_id = await workflow.execute_activity(
                get_sandbox_for_setup,
                get_sandbox_input,
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            # Clone repository
            clone_input = CloneRepositoryInput(
                sandbox_id=sandbox_id,
                repository=repository,
                github_integration_id=github_integration_id,
            )
            await workflow.execute_activity(
                clone_repository,
                clone_input,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            # Setup repository
            setup_repo_input = SetupRepositoryInput(
                sandbox_id=sandbox_id,
                repository=repository,
            )
            await workflow.execute_activity(
                setup_repository,
                setup_repo_input,
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )

            # Create and finalize snapshot (initiates, polls, and finalizes in one activity)
            snapshot_input = CreateSnapshotInput(
                sandbox_id=sandbox_id,
                github_integration_id=github_integration_id,
                team_id=team_id,
                repository=repository,
            )
            snapshot_id = await workflow.execute_activity(
                create_snapshot,
                snapshot_input,
                start_to_close_timeout=timedelta(minutes=25),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            return snapshot_id

        finally:
            # Cleanup setup sandbox
            if sandbox_id:
                try:
                    cleanup_input = CleanupSandboxInput(sandbox_id=sandbox_id)
                    await workflow.execute_activity(
                        cleanup_sandbox,
                        cleanup_input,
                        start_to_close_timeout=timedelta(minutes=5),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )
                except Exception:
                    pass

    async def _create_sandbox_from_snapshot(self, snapshot_id: str) -> str:
        """Create a sandbox from a snapshot."""
        create_sandbox_input = CreateSandboxFromSnapshotInput(snapshot_id=snapshot_id)
        return await workflow.execute_activity(
            create_sandbox_from_snapshot,
            create_sandbox_input,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

    async def _execute_task_in_sandbox(self, sandbox_id: str, task_id: str, repository: str) -> None:
        """Execute the task in the sandbox."""
        execute_input = ExecuteTaskInput(
            sandbox_id=sandbox_id,
            task_id=task_id,
            repository=repository,
        )
        await workflow.execute_activity(
            execute_task_in_sandbox,
            execute_input,
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
