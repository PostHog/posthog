import os
import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import cast

import pytest
from unittest.mock import patch

from django.conf import settings

from asgiref.sync import sync_to_async
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.services.sandbox import Sandbox, SandboxStatus
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

    These tests create actual sandboxes and snapshots, only mocking the setup command
    to avoid running full dependency installation.
    """

    async def _run_workflow(
        self,
        github_integration_id: int,
        repository: str,
        team_id: int,
        mock_setup_command: str = "echo 'setup complete'",
    ) -> CreateSnapshotForRepositoryOutput:
        workflow_id = str(uuid.uuid4())

        with patch(
            "products.tasks.backend.temporal.create_snapshot.activities.setup_repository.Sandbox._get_setup_command"
        ) as mock_setup:
            mock_setup.return_value = mock_setup_command

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

    async def test_workflow_creates_snapshot_successfully(self, github_integration, test_team):
        created_snapshots: list[SandboxSnapshot] = []

        try:
            result = await self._run_workflow(
                github_integration_id=github_integration.id,
                repository="posthog/posthog-js",
                team_id=test_team.id,
            )

            assert result.success is True
            assert result.snapshot_id is not None
            assert result.error is None

            snapshots_query = SandboxSnapshot.objects.filter(
                integration=github_integration, status=SandboxSnapshot.Status.COMPLETE
            ).order_by("-created_at")
            snapshots = cast(list[SandboxSnapshot], await sync_to_async(lambda: list(snapshots_query))())

            assert len(snapshots) >= 1
            latest_snapshot = snapshots[0]
            assert "posthog/posthog-js" in latest_snapshot.repos
            assert latest_snapshot.status == SandboxSnapshot.Status.COMPLETE
            assert latest_snapshot.external_id is not None

            created_snapshots.append(latest_snapshot)

        finally:
            for snapshot in created_snapshots:
                await self._cleanup_snapshot(snapshot)

    async def test_workflow_snapshot_contains_only_specified_repository(self, github_integration, test_team):
        created_snapshots: list[SandboxSnapshot] = []

        try:
            result = await self._run_workflow(
                github_integration_id=github_integration.id,
                repository="posthog/posthog-js",
                team_id=test_team.id,
            )

            assert result.success is True

            snapshot = await sync_to_async(SandboxSnapshot.objects.get)(id=result.snapshot_id)
            created_snapshots.append(snapshot)

            assert snapshot.repos == ["posthog/posthog-js"]
            assert len(snapshot.repos) == 1

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

    async def test_workflow_handles_clone_failure(self, github_integration, test_team):
        result = await self._run_workflow(
            github_integration_id=github_integration.id,
            repository="posthog/nonexistent-repo-12345",
            team_id=test_team.id,
        )

        assert result.success is False
        assert result.error is not None
        assert result.snapshot_id is None

    async def test_workflow_handles_setup_failure(self, github_integration, test_team):
        result = await self._run_workflow(
            github_integration_id=github_integration.id,
            repository="posthog/posthog-js",
            team_id=test_team.id,
            mock_setup_command="exit 1",
        )

        assert result.success is False
        assert result.error is not None
        assert result.snapshot_id is None

    async def test_workflow_cleans_up_sandbox_on_success(self, github_integration, test_team):
        created_snapshots: list[SandboxSnapshot] = []

        try:
            result = await self._run_workflow(
                github_integration_id=github_integration.id,
                repository="posthog/posthog-js",
                team_id=test_team.id,
            )

            assert result.success is True
            assert result.sandbox_id is not None

            if result.snapshot_id:
                snapshot = await sync_to_async(SandboxSnapshot.objects.get)(id=result.snapshot_id)
                created_snapshots.append(snapshot)

            await asyncio.sleep(10)
            sandbox = Sandbox.get_by_id(result.sandbox_id)
            assert sandbox.get_status() == SandboxStatus.SHUTDOWN

        finally:
            for snapshot in created_snapshots:
                await self._cleanup_snapshot(snapshot)

    async def test_workflow_cleans_up_sandbox_on_failure(self, github_integration, test_team):
        result = await self._run_workflow(
            github_integration_id=github_integration.id,
            repository="posthog/posthog-js",
            team_id=test_team.id,
            mock_setup_command="exit 1",
        )

        assert result.success is False
        assert result.sandbox_id is not None

        await asyncio.sleep(10)
        sandbox = Sandbox.get_by_id(result.sandbox_id)
        assert sandbox.get_status() == SandboxStatus.SHUTDOWN

    async def test_multiple_runs_create_separate_snapshots(self, github_integration, test_team):
        created_snapshots: list[SandboxSnapshot] = []

        try:
            result1 = await self._run_workflow(
                github_integration_id=github_integration.id,
                repository="posthog/posthog-js",
                team_id=test_team.id,
            )

            assert result1.success is True
            snapshot1 = await sync_to_async(SandboxSnapshot.objects.get)(id=result1.snapshot_id)
            created_snapshots.append(snapshot1)

            result2 = await self._run_workflow(
                github_integration_id=github_integration.id,
                repository="posthog/posthog-js",
                team_id=test_team.id,
            )

            assert result2.success is True
            snapshot2 = await sync_to_async(SandboxSnapshot.objects.get)(id=result2.snapshot_id)
            created_snapshots.append(snapshot2)

            assert result1.snapshot_id != result2.snapshot_id
            assert snapshot1.repos == ["posthog/posthog-js"]
            assert snapshot2.repos == ["posthog/posthog-js"]

        finally:
            for snapshot in created_snapshots:
                await self._cleanup_snapshot(snapshot)
