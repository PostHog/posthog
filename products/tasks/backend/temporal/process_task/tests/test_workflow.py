import os
import uuid
import random
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from django.conf import settings

from asgiref.sync import sync_to_async
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxStatus, SandboxTemplate
from products.tasks.backend.temporal.process_task.activities import (
    cleanup_sandbox,
    get_sandbox_for_repository,
    get_task_processing_context,
    start_agent_server,
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

    The workflow now starts an agent-server and waits for a completion signal
    or timeout. Tests verify the workflow starts correctly and handles signals.
    """

    async def _run_workflow_with_signal(
        self,
        run_id: str,
        signal_status: str = "completed",
        signal_error: str | None = None,
        create_pr: bool = True,
    ) -> ProcessTaskOutput:
        workflow_id = str(uuid.uuid4())
        workflow_input = ProcessTaskInput(run_id=str(run_id), create_pr=create_pr)

        async with (
            await WorkflowEnvironment.start_time_skipping() as env,
            Worker(
                env.client,
                task_queue=settings.TASKS_TASK_QUEUE,
                workflows=[ProcessTaskWorkflow],
                activities=[
                    get_task_processing_context,
                    get_sandbox_for_repository,
                    start_agent_server,
                    cleanup_sandbox,
                    track_workflow_event,
                    update_task_run_status,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=10),
            ),
        ):
            handle = await env.client.start_workflow(
                ProcessTaskWorkflow.run,
                workflow_input,
                id=workflow_id,
                task_queue=settings.TASKS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
                execution_timeout=timedelta(minutes=60),
            )

            await asyncio.sleep(2)

            await handle.signal(ProcessTaskWorkflow.complete_task, args=[signal_status, signal_error])

            result = await handle.result()

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

    async def test_workflow_starts_agent_server_and_waits_for_signal(self, test_task_run, github_integration):
        """Workflow starts agent-server and completes when signaled."""
        snapshot = await sync_to_async(self._create_test_snapshot)(github_integration)

        try:
            result = await self._run_workflow_with_signal(test_task_run.id, signal_status="completed")

            assert result.success is True
            assert result.sandbox_id is not None

        finally:
            await sync_to_async(snapshot.delete)()

    async def test_workflow_handles_failure_signal(self, test_task_run, github_integration):
        """Workflow handles failure signal correctly."""
        snapshot = await sync_to_async(self._create_test_snapshot)(github_integration)

        try:
            result = await self._run_workflow_with_signal(
                test_task_run.id, signal_status="failed", signal_error="Test error"
            )

            assert result.success is True
            assert result.sandbox_id is not None

        finally:
            await sync_to_async(snapshot.delete)()

    async def test_workflow_cleans_up_sandbox(self, test_task_run, github_integration):
        """Workflow cleans up sandbox after completion."""
        snapshot = await sync_to_async(self._create_test_snapshot)(github_integration)

        try:
            result = await self._run_workflow_with_signal(test_task_run.id)

            assert result.success is True
            assert result.sandbox_id is not None

            await asyncio.sleep(10)

            sandbox = Sandbox.get_by_id(result.sandbox_id)
            assert sandbox.get_status() == SandboxStatus.SHUTDOWN

        finally:
            await sync_to_async(snapshot.delete)()

    async def test_workflow_handles_missing_task(self):
        fake_task_id = str(uuid.uuid4())

        workflow_id = str(uuid.uuid4())
        workflow_input = ProcessTaskInput(run_id=fake_task_id)

        async with (
            await WorkflowEnvironment.start_time_skipping() as env,
            Worker(
                env.client,
                task_queue=settings.TASKS_TASK_QUEUE,
                workflows=[ProcessTaskWorkflow],
                activities=[
                    get_task_processing_context,
                    get_sandbox_for_repository,
                    start_agent_server,
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

        assert result.success is False
        assert result.error is not None
