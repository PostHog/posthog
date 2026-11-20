import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from django.conf import settings

from asgiref.sync import sync_to_async
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.test.waiting import wait_until

from products.tasks.backend.logic.services.sandbox import Sandbox, SandboxStatus
from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.temporal.create_snapshot.activities import (
    cleanup_sandbox,
    clone_repository,
    create_sandbox,
    create_snapshot,
    get_snapshot_context,
    setup_repository,
)
from products.tasks.backend.temporal.create_snapshot.workflow import (
    CreateSnapshotForRepositoryInput,
    CreateSnapshotForRepositoryOutput,
    CreateSnapshotForRepositoryWorkflow,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


@pytest.mark.skipif(
    not os.environ.get("MODAL_TOKEN_ID") or not os.environ.get("MODAL_TOKEN_SECRET"),
    reason="MODAL_TOKEN_ID and MODAL_TOKEN_SECRET environment variables not set",
)
class TestCreateSnapshotForRepositoryWorkflow:
    """
    End-to-end workflow tests for snapshot creation using real Modal sandboxes.

    These tests create actual sandboxes and snapshots. Setup is now a no-op
    (repository setup happens via agent-server).
    """

    async def _run_workflow(
        self,
        github_integration_id: int,
        repository: str,
        team_id: int,
    ) -> CreateSnapshotForRepositoryOutput:
        workflow_id = str(uuid.uuid4())

        async with (
            await WorkflowEnvironment.start_time_skipping() as env,
            Worker(
                env.client,
                task_queue=settings.TASKS_TASK_QUEUE,
                workflows=[CreateSnapshotForRepositoryWorkflow],
                activities=[
                    get_snapshot_context,
                    create_sandbox,
                    clone_repository,
                    setup_repository,
                    create_snapshot,
                    cleanup_sandbox,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=10),
            ),
        ):
            result = await env.client.execute_workflow(
                CreateSnapshotForRepositoryWorkflow.run,
                CreateSnapshotForRepositoryInput(
                    github_integration_id=github_integration_id,
                    repository=repository,
                    team_id=team_id,
                ),
                id=workflow_id,
                task_queue=settings.TASKS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
                execution_timeout=timedelta(minutes=60),
            )

        return result

    async def _cleanup_snapshot(self, snapshot: SandboxSnapshot) -> None:
        try:
            if snapshot.external_id:
                Sandbox.delete_snapshot(snapshot.external_id)
            await sync_to_async(snapshot.delete)()
        except Exception:
            pass

    async def test_successful_runs_snapshot_only_the_repository_and_shut_down_their_sandboxes(
        self, github_integration, test_team
    ):
        created_snapshots: list[SandboxSnapshot] = []

        try:
            results = []
            sandbox_ids: list[str] = []
            for _ in range(2):
                result = await self._run_workflow(
                    github_integration_id=github_integration.id,
                    repository="posthog/posthog-js",
                    team_id=test_team.id,
                )
                assert result.success is True
                assert result.error is None
                assert result.snapshot_id is not None
                assert result.sandbox_id is not None
                created_snapshots.append(await sync_to_async(SandboxSnapshot.objects.get)(id=result.snapshot_id))
                results.append(result)
                sandbox_ids.append(result.sandbox_id)

            assert results[0].snapshot_id != results[1].snapshot_id
            for snapshot in created_snapshots:
                assert snapshot.status == SandboxSnapshot.Status.COMPLETE
                assert snapshot.external_id is not None
                assert snapshot.repos == ["posthog/posthog-js"]
            for sandbox_id in sandbox_ids:
                _wait_for_sandbox_shutdown(sandbox_id)

        finally:
            for snapshot in created_snapshots:
                await self._cleanup_snapshot(snapshot)

    async def test_workflow_handles_invalid_integration(self, test_team):
        invalid_integration_id = 999999

        result = await self._run_workflow(
            github_integration_id=invalid_integration_id,
            repository="posthog/posthog-js",
            team_id=test_team.id,
        )

        assert result.success is False
        assert result.error is not None
        assert result.snapshot_id is None

    async def test_clone_failure_fails_the_run_and_shuts_down_its_sandbox(self, github_integration, test_team):
        result = await self._run_workflow(
            github_integration_id=github_integration.id,
            repository="posthog/nonexistent-repo-12345",
            team_id=test_team.id,
        )

        assert result.success is False
        assert result.error is not None
        assert result.snapshot_id is None
        assert result.sandbox_id is not None
        _wait_for_sandbox_shutdown(result.sandbox_id)


def _wait_for_sandbox_shutdown(sandbox_id: str) -> None:
    wait_until(
        lambda: Sandbox.get_by_id(sandbox_id).get_status() == SandboxStatus.SHUTDOWN,
        timeout=60,
        interval=1,
        message=f"sandbox {sandbox_id} never shut down",
    )
