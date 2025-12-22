import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from .activities import (
    CleanupSandboxInput,
    CloneRepositoryInput,
    CreateSandboxInput,
    CreateSnapshotInput,
    GetSnapshotContextInput,
    SetupRepositoryInput,
    SnapshotContext,
    cleanup_sandbox,
    clone_repository,
    create_sandbox,
    create_snapshot,
    get_snapshot_context,
    setup_repository,
)


@dataclass
class CreateSnapshotForRepositoryInput:
    github_integration_id: int
    repository: str
    team_id: int


@dataclass
class CreateSnapshotForRepositoryOutput:
    success: bool
    snapshot_id: Optional[str] = None
    sandbox_id: Optional[str] = None
    error: Optional[str] = None


@workflow.defn(name="create-snapshot-for-repository")
class CreateSnapshotForRepositoryWorkflow(PostHogWorkflow):
    def __init__(self) -> None:
        self._context: Optional[SnapshotContext] = None

    @property
    def context(self) -> SnapshotContext:
        if self._context is None:
            raise RuntimeError("context accessed before being set")
        return self._context

    @staticmethod
    def parse_inputs(inputs: list[str]) -> CreateSnapshotForRepositoryInput:
        loaded = json.loads(inputs[0])
        return CreateSnapshotForRepositoryInput(
            github_integration_id=loaded["github_integration_id"],
            repository=loaded["repository"],
            team_id=loaded["team_id"],
        )

    @workflow.run
    async def run(self, input: CreateSnapshotForRepositoryInput) -> CreateSnapshotForRepositoryOutput:
        sandbox_id = None

        try:
            self._context = await self._get_snapshot_context(input)

            sandbox_output = await self._create_sandbox()
            sandbox_id = sandbox_output.sandbox_id

            await self._clone_repository(sandbox_id)

            await self._setup_repository(sandbox_id)

            snapshot_id = await self._create_snapshot(sandbox_id)

            return CreateSnapshotForRepositoryOutput(
                success=True,
                snapshot_id=snapshot_id,
                sandbox_id=sandbox_id,
            )

        except Exception as e:
            return CreateSnapshotForRepositoryOutput(
                success=False,
                sandbox_id=sandbox_id,
                error=str(e),
            )

        finally:
            if sandbox_id:
                await self._cleanup_sandbox(sandbox_id)

    async def _get_snapshot_context(self, input: CreateSnapshotForRepositoryInput) -> SnapshotContext:
        return await workflow.execute_activity(
            get_snapshot_context,
            GetSnapshotContextInput(
                github_integration_id=input.github_integration_id,
                repository=input.repository,
                team_id=input.team_id,
            ),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _create_sandbox(self):
        return await workflow.execute_activity(
            create_sandbox,
            CreateSandboxInput(context=self.context),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _clone_repository(self, sandbox_id: str) -> str:
        return await workflow.execute_activity(
            clone_repository,
            CloneRepositoryInput(context=self.context, sandbox_id=sandbox_id),
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _setup_repository(self, sandbox_id: str) -> str:
        return await workflow.execute_activity(
            setup_repository,
            SetupRepositoryInput(context=self.context, sandbox_id=sandbox_id),
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _create_snapshot(self, sandbox_id: str) -> str:
        return await workflow.execute_activity(
            create_snapshot,
            CreateSnapshotInput(context=self.context, sandbox_id=sandbox_id),
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _cleanup_sandbox(self, sandbox_id: str) -> None:
        await workflow.execute_activity(
            cleanup_sandbox,
            CleanupSandboxInput(sandbox_id=sandbox_id),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
