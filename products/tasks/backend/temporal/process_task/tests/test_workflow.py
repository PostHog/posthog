import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import cast

import pytest
from unittest.mock import patch

from asgiref.sync import sync_to_async
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog import constants

from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.services.sandbox_environment import SandboxEnvironment, SandboxEnvironmentStatus
from products.tasks.backend.temporal.process_task.activities.check_snapshot_exists_for_repository import (
    check_snapshot_exists_for_repository,
)
from products.tasks.backend.temporal.process_task.activities.cleanup_personal_api_key import cleanup_personal_api_key
from products.tasks.backend.temporal.process_task.activities.cleanup_sandbox import cleanup_sandbox
from products.tasks.backend.temporal.process_task.activities.clone_repository import clone_repository
from products.tasks.backend.temporal.process_task.activities.create_sandbox_from_snapshot import (
    create_sandbox_from_snapshot,
)
from products.tasks.backend.temporal.process_task.activities.create_snapshot import create_snapshot
from products.tasks.backend.temporal.process_task.activities.execute_task_in_sandbox import execute_task_in_sandbox
from products.tasks.backend.temporal.process_task.activities.get_sandbox_for_setup import get_sandbox_for_setup
from products.tasks.backend.temporal.process_task.activities.get_task_details import get_task_details
from products.tasks.backend.temporal.process_task.activities.inject_github_token import inject_github_token
from products.tasks.backend.temporal.process_task.activities.inject_personal_api_key import inject_personal_api_key
from products.tasks.backend.temporal.process_task.activities.setup_repository import setup_repository
from products.tasks.backend.temporal.process_task.activities.tests.constants import POSTHOG_JS_SNAPSHOT
from products.tasks.backend.temporal.process_task.activities.track_workflow_event import track_workflow_event
from products.tasks.backend.temporal.process_task.workflow import ProcessTaskOutput, ProcessTaskWorkflow

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


@pytest.mark.skipif(not os.environ.get("RUNLOOP_API_KEY"), reason="RUNLOOP_API_KEY environment variable not set")
class TestProcessTaskWorkflow:
    """
    End-to-end workflow tests using real Runloop sandboxes.

    These tests create actual sandboxes and snapshots, only mocking the task execution command
    to avoid running the full AI agent. This allows us to verify:
    - Snapshot creation and reuse
    - Sandbox lifecycle management
    - Proper cleanup on success and failure
    """

    async def _run_workflow(self, task_id: str, mock_task_command: str = "echo 'task complete'") -> ProcessTaskOutput:
        workflow_id = str(uuid.uuid4())

        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.setup_repository.SandboxAgent._get_setup_command"
            ) as mock_setup,
            patch(
                "products.tasks.backend.temporal.process_task.activities.execute_task_in_sandbox.SandboxAgent._get_task_command"
            ) as mock_task,
        ):
            mock_setup.return_value = "pnpm install"
            mock_task.return_value = mock_task_command

            async with (
                await WorkflowEnvironment.start_time_skipping() as env,
                Worker(
                    env.client,
                    task_queue=constants.settings.TASKS_TASK_QUEUE,
                    workflows=[ProcessTaskWorkflow],
                    activities=[
                        get_task_details,
                        check_snapshot_exists_for_repository,
                        get_sandbox_for_setup,
                        clone_repository,
                        setup_repository,
                        create_snapshot,
                        create_sandbox_from_snapshot,
                        inject_github_token,
                        inject_personal_api_key,
                        execute_task_in_sandbox,
                        cleanup_sandbox,
                        cleanup_personal_api_key,
                        track_workflow_event,
                    ],
                    workflow_runner=UnsandboxedWorkflowRunner(),
                    activity_executor=ThreadPoolExecutor(max_workers=10),
                ),
            ):
                result = await env.client.execute_workflow(
                    ProcessTaskWorkflow.run,
                    task_id,
                    id=workflow_id,
                    task_queue=constants.settings.TASKS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=timedelta(minutes=60),
                )

        return result

    async def _verify_file_in_sandbox(self, sandbox_id: str, filepath: str) -> bool:
        """Verify a file exists in a sandbox."""
        sandbox = await SandboxEnvironment.get_by_id(sandbox_id)
        result = await sandbox.execute(f"test -f {filepath} && echo 'exists' || echo 'missing'")
        return "exists" in result.stdout

    async def test_workflow_with_existing_snapshot_reuses_snapshot(self, test_task, github_integration):
        snapshot, _ = await sync_to_async(SandboxSnapshot.objects.get_or_create)(
            external_id=POSTHOG_JS_SNAPSHOT["external_id"],
            defaults={
                "integration": github_integration,
                "repos": POSTHOG_JS_SNAPSHOT["repos"],
                "status": SandboxSnapshot.Status.COMPLETE,
            },
        )

        try:
            result = await self._run_workflow(test_task.id)

            assert result.success is True
            assert result.task_result is not None
            assert result.task_result.exit_code == 0
            assert "task complete" in result.task_result.stdout

            snapshots_query = SandboxSnapshot.objects.filter(integration=github_integration).order_by("-created_at")
            snapshots = cast(list[SandboxSnapshot], await sync_to_async(list)(snapshots_query))  # type: ignore[call-arg]
            assert len(snapshots) == 1
            assert snapshots[0].id == snapshot.id
            assert "posthog/posthog-js" in snapshots[0].repos

        finally:
            await sync_to_async(snapshot.delete)()

    async def test_workflow_creates_snapshot_for_new_repository(self, test_task, github_integration):
        created_snapshots = []

        try:
            result = await self._run_workflow(test_task.id)

            assert result.success is True
            assert result.task_result is not None
            assert result.task_result.exit_code == 0

            snapshots_query = SandboxSnapshot.objects.filter(
                integration=github_integration, status=SandboxSnapshot.Status.COMPLETE
            ).order_by("-created_at")
            snapshots = cast(list[SandboxSnapshot], await sync_to_async(list)(snapshots_query))  # type: ignore[call-arg]

            assert len(snapshots) >= 1
            latest_snapshot = snapshots[0]
            assert "posthog/posthog-js" in latest_snapshot.repos
            assert latest_snapshot.status == SandboxSnapshot.Status.COMPLETE
            assert latest_snapshot.external_id is not None

            created_snapshots.append(latest_snapshot)

        finally:
            for snapshot in created_snapshots:
                try:
                    if snapshot.external_id:
                        await SandboxEnvironment.delete_snapshot(snapshot.external_id)
                    await sync_to_async(snapshot.delete)()
                except Exception:
                    pass

    async def test_workflow_executes_task_in_sandbox(self, test_task, github_integration):
        snapshot = await sync_to_async(SandboxSnapshot.objects.create)(
            integration=github_integration,
            external_id=POSTHOG_JS_SNAPSHOT["external_id"],
            repos=POSTHOG_JS_SNAPSHOT["repos"],
            status=SandboxSnapshot.Status.COMPLETE,
        )

        custom_message = f"workflow_test_{uuid.uuid4().hex[:8]}"

        try:
            result = await self._run_workflow(test_task.id, mock_task_command=f"echo '{custom_message}'")

            assert result.success is True
            assert result.task_result is not None
            assert result.task_result.exit_code == 0
            assert custom_message in result.task_result.stdout

        finally:
            await sync_to_async(snapshot.delete)()

    async def test_workflow_cleans_up_sandbox_on_success(self, test_task, github_integration):
        snapshot = await sync_to_async(SandboxSnapshot.objects.create)(
            integration=github_integration,
            external_id=POSTHOG_JS_SNAPSHOT["external_id"],
            repos=POSTHOG_JS_SNAPSHOT["repos"],
            status=SandboxSnapshot.Status.COMPLETE,
        )

        try:
            result = await self._run_workflow(test_task.id)

            assert result.success is True
            assert result.task_result is not None
            assert result.sandbox_id is not None

            sandbox = await SandboxEnvironment.get_by_id(result.sandbox_id)
            assert sandbox.status == SandboxEnvironmentStatus.SHUTDOWN.value

        finally:
            await sync_to_async(snapshot.delete)()

    async def test_workflow_cleans_up_sandbox_on_failure(self, test_task, github_integration):
        snapshot = await sync_to_async(SandboxSnapshot.objects.create)(
            integration=github_integration,
            external_id=POSTHOG_JS_SNAPSHOT["external_id"],
            repos=POSTHOG_JS_SNAPSHOT["repos"],
            status=SandboxSnapshot.Status.COMPLETE,
        )

        try:
            result = await self._run_workflow(test_task.id, mock_task_command="exit 1")

            assert result.success is False
            assert result.error is not None
            assert result.task_result is None

            assert result.sandbox_id is not None
            sandbox_id = result.sandbox_id

            sandbox = await SandboxEnvironment.get_by_id(sandbox_id)
            assert sandbox.status == SandboxEnvironmentStatus.SHUTDOWN.value

        finally:
            await sync_to_async(snapshot.delete)()

    async def test_workflow_handles_missing_task(self):
        fake_task_id = str(uuid.uuid4())

        result = await self._run_workflow(fake_task_id)

        assert result.success is False
        assert result.error is not None
        assert "activity task failed" in result.error.lower() or "failed" in result.error.lower()

    async def test_workflow_full_cycle_no_snapshot(self, test_task, github_integration):
        created_snapshots = []

        try:
            result = await self._run_workflow(test_task.id)

            assert result.success is True
            assert result.task_result is not None
            assert result.task_result.exit_code == 0

            snapshots_query = SandboxSnapshot.objects.filter(
                integration=github_integration, status=SandboxSnapshot.Status.COMPLETE
            ).order_by("-created_at")
            snapshots = cast(list[SandboxSnapshot], await sync_to_async(list)(snapshots_query))  # type: ignore[call-arg]

            assert len(snapshots) >= 1
            latest_snapshot = snapshots[0]
            assert "posthog/posthog-js" in latest_snapshot.repos
            assert latest_snapshot.status == SandboxSnapshot.Status.COMPLETE

            created_snapshots.append(latest_snapshot)

            result2 = await self._run_workflow(test_task.id)

            assert result2.success is True
            assert result2.task_result is not None

            snapshots_after_query = SandboxSnapshot.objects.filter(
                integration=github_integration, status=SandboxSnapshot.Status.COMPLETE
            ).order_by("-created_at")
            snapshots_after = cast(list[SandboxSnapshot], await sync_to_async(list)(snapshots_after_query))  # type: ignore[call-arg]
            assert len(snapshots_after) == len(snapshots)

        finally:
            for snapshot in created_snapshots:
                try:
                    if snapshot.external_id:
                        await SandboxEnvironment.delete_snapshot(snapshot.external_id)
                    await sync_to_async(snapshot.delete)()
                except Exception:
                    pass
