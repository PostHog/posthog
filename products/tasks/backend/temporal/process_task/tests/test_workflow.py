import os
import uuid
import random
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from unittest.mock import patch

from django.conf import settings

from asgiref.sync import sync_to_async
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxStatus, SandboxTemplate
from products.tasks.backend.temporal.process_task.activities import (
    cleanup_sandbox,
    execute_task_in_sandbox,
    get_sandbox_for_repository,
    get_task_processing_context,
    track_workflow_event,
    update_task_run_status,
)
from products.tasks.backend.temporal.process_task.workflow import (
    ProcessTaskInput,
    ProcessTaskOutput,
    ProcessTaskWorkflow,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


@pytest.mark.skipif(
    not os.environ.get("MODAL_TOKEN_ID") or not os.environ.get("MODAL_TOKEN_SECRET"),
    reason="MODAL_TOKEN_ID and MODAL_TOKEN_SECRET environment variables not set",
)
class TestProcessTaskWorkflow:
    """
    End-to-end workflow tests using real Modal sandboxes.

    These tests create actual sandboxes, only mocking the task execution command
    to avoid running the full AI agent. Snapshot creation is triggered asynchronously
    when no snapshot exists.
    """

    async def _run_workflow(
        self, run_id: str, mock_task_command: str = "echo 'task complete'", create_pr: bool = True
    ) -> ProcessTaskOutput:
        workflow_id = str(uuid.uuid4())
        workflow_input = ProcessTaskInput(run_id=str(run_id), create_pr=create_pr)

        with patch(
            "products.tasks.backend.temporal.process_task.activities.execute_task_in_sandbox.Sandbox._get_task_command"
        ) as mock_task:
            mock_task.return_value = mock_task_command

            async with (
                await WorkflowEnvironment.start_time_skipping() as env,
                Worker(
                    env.client,
                    task_queue=settings.TASKS_TASK_QUEUE,
                    workflows=[ProcessTaskWorkflow],
                    activities=[
                        get_task_processing_context,
                        get_sandbox_for_repository,
                        execute_task_in_sandbox,
                        cleanup_sandbox,
                        track_workflow_event,
                        update_task_run_status,
                    ],
                    workflow_runner=UnsandboxedWorkflowRunner(),
                    activity_executor=ThreadPoolExecutor(max_workers=10),
                ),
            ):
                result = await env.client.execute_workflow(
                    ProcessTaskWorkflow.run,
                    workflow_input,
                    id=workflow_id,
                    task_queue=settings.TASKS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=timedelta(minutes=60),
                )

        return result

    def _create_test_snapshot(self, github_integration):
        sandbox = None
        try:
            config = SandboxConfig(
                name=f"test-workflow-snapshot-{random.randint(1, 99999)}",
                template=SandboxTemplate.DEFAULT_BASE,
            )
            sandbox = Sandbox.create(config)

            clone_result = sandbox.clone_repository("posthog/posthog-js", github_token="")
            if clone_result.exit_code != 0:
                raise Exception(f"Failed to clone repository: {clone_result.stderr}")

            snapshot_id = sandbox.create_snapshot()

            snapshot = SandboxSnapshot.objects.create(
                integration=github_integration,
                repos=["posthog/posthog-js"],
                external_id=snapshot_id,
                status=SandboxSnapshot.Status.COMPLETE,
            )
            return snapshot
        finally:
            if sandbox:
                sandbox.destroy()

    async def test_workflow_with_existing_snapshot_reuses_snapshot(self, test_task_run, github_integration):
        snapshot = await sync_to_async(self._create_test_snapshot)(github_integration)

        try:
            result = await self._run_workflow(test_task_run.id)

            assert result.success is True
            assert result.task_result is not None
            assert result.task_result.exit_code == 0
            assert "task complete" in result.task_result.stdout

        finally:
            await sync_to_async(snapshot.delete)()

    async def test_workflow_without_snapshot_still_succeeds(self, test_task_run, github_integration):
        """When no snapshot exists, workflow should still complete successfully using base image."""
        with patch.object(ProcessTaskWorkflow, "_trigger_snapshot_workflow"):
            result = await self._run_workflow(test_task_run.id)

            assert result.success is True
            assert result.task_result is not None
            assert result.task_result.exit_code == 0

    async def test_workflow_executes_task_in_sandbox(self, test_task_run, github_integration):
        snapshot = await sync_to_async(self._create_test_snapshot)(github_integration)

        custom_message = f"workflow_test_{uuid.uuid4().hex[:8]}"

        try:
            result = await self._run_workflow(test_task_run.id, mock_task_command=f"echo '{custom_message}'")

            assert result.success is True
            assert result.task_result is not None
            assert result.task_result.exit_code == 0
            assert custom_message in result.task_result.stdout

        finally:
            await sync_to_async(snapshot.delete)()

    async def test_workflow_cleans_up_sandbox_on_success(self, test_task_run, github_integration):
        snapshot = await sync_to_async(self._create_test_snapshot)(github_integration)

        try:
            result = await self._run_workflow(test_task_run.id)

            assert result.success is True
            assert result.task_result is not None
            assert result.sandbox_id is not None

            await asyncio.sleep(10)

            sandbox = Sandbox.get_by_id(result.sandbox_id)
            assert sandbox.get_status() == SandboxStatus.SHUTDOWN

        finally:
            await sync_to_async(snapshot.delete)()

    async def test_workflow_cleans_up_sandbox_on_failure(self, test_task_run, github_integration):
        snapshot = await sync_to_async(self._create_test_snapshot)(github_integration)

        try:
            result = await self._run_workflow(test_task_run.id, mock_task_command="exit 1")

            assert result.success is False
            assert result.error is not None
            assert result.task_result is None

            assert result.sandbox_id is not None
            sandbox_id = result.sandbox_id

            await asyncio.sleep(10)
            sandbox = Sandbox.get_by_id(sandbox_id)
            assert sandbox.get_status() == SandboxStatus.SHUTDOWN

        finally:
            await sync_to_async(snapshot.delete)()

    async def test_workflow_handles_missing_task(self):
        fake_task_id = str(uuid.uuid4())

        result = await self._run_workflow(fake_task_id)

        assert result.success is False
        assert result.error is not None
        assert "activity task failed" in result.error.lower() or "failed" in result.error.lower()
