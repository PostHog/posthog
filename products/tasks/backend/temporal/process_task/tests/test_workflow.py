import os
import uuid
import random
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from unittest.mock import AsyncMock

from django.conf import settings

from asgiref.sync import sync_to_async
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, RetryState
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxStatus, SandboxTemplate
from products.tasks.backend.temporal.process_task import workflow as process_task_workflow_module
from products.tasks.backend.temporal.process_task.activities import (
    CreateSandboxForRepositoryOutput,
    GetSandboxForRepositoryOutput,
    PrepareSandboxForRepositoryOutput,
    TaskProcessingContext,
    checkout_branch_in_sandbox,
    cleanup_sandbox,
    clone_repository_in_sandbox,
    create_sandbox_for_repository,
    emit_progress_activity,
    forward_pending_user_message,
    get_task_processing_context,
    inject_fresh_tokens_on_resume,
    prepare_sandbox_for_repository,
    read_sandbox_logs,
    start_agent_server,
    track_workflow_event,
    update_task_run_status,
)
from products.tasks.backend.temporal.process_task.workflow import (
    ProcessTaskInput,
    ProcessTaskOutput,
    ProcessTaskWorkflow,
)


def _build_context(
    *,
    github_integration_id: int | None,
    repository: str | None = "posthog/posthog-js",
    state: dict | None = None,
) -> TaskProcessingContext:
    return TaskProcessingContext(
        task_id="task-id",
        run_id="run-id",
        team_id=1,
        team_uuid="team-uuid",
        organization_id="organization-id",
        github_integration_id=github_integration_id,
        repository=repository,
        distinct_id="distinct-id",
        create_pr=True,
        state=state or {},
        _branch="feature-branch",
    )


@pytest.mark.django_db
def test_activity_error_properties_includes_failed_activity_context():
    error = ActivityError(
        "Activity task timed out",
        scheduled_event_id=10,
        started_event_id=11,
        identity="worker-1",
        activity_type="get_pr_context",
        activity_id="activity-1",
        retry_state=RetryState.TIMEOUT,
    )
    error.__cause__ = TimeoutError("start-to-close timeout")

    assert ProcessTaskWorkflow._activity_error_properties(error) == {
        "temporal_activity_id": "activity-1",
        "temporal_activity_type": "get_pr_context",
        "temporal_activity_identity": "worker-1",
        "temporal_activity_retry_state": "TIMEOUT",
        "temporal_activity_scheduled_event_id": 10,
        "temporal_activity_started_event_id": 11,
        "cause_error_type": "TimeoutError",
        "cause_error_message": "start-to-close timeout",
    }


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
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
                    forward_pending_user_message,
                    get_task_processing_context,
                    prepare_sandbox_for_repository,
                    create_sandbox_for_repository,
                    inject_fresh_tokens_on_resume,
                    clone_repository_in_sandbox,
                    checkout_branch_in_sandbox,
                    start_agent_server,
                    read_sandbox_logs,
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
                    forward_pending_user_message,
                    get_task_processing_context,
                    prepare_sandbox_for_repository,
                    create_sandbox_for_repository,
                    inject_fresh_tokens_on_resume,
                    clone_repository_in_sandbox,
                    checkout_branch_in_sandbox,
                    start_agent_server,
                    read_sandbox_logs,
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


@pytest.mark.django_db
class TestProcessTaskWorkflowUnit:
    @pytest.mark.parametrize(
        "state, expected",
        [
            ({"mode": "interactive", "pending_user_message": "this is nice"}, False),
            ({"mode": "background", "pending_user_message": "this is nice"}, True),
            (
                {
                    "mode": "background",
                    "pending_user_message": "this is nice",
                    "resume_from_run_id": "previous-run-id",
                },
                False,
            ),
        ],
    )
    def test_should_forward_pending_message(self, state: dict, expected: bool):
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(
            github_integration_id=123,
            state=state,
        )

        assert workflow._should_forward_pending_user_message() is expected

    async def test_run_cleans_up_sandbox_when_provisioning_fails_after_creation(self, monkeypatch):
        workflow = ProcessTaskWorkflow()
        get_task_processing_context_mock = AsyncMock(return_value=_build_context(github_integration_id=123))
        update_task_run_status_mock = AsyncMock()
        track_workflow_event_mock = AsyncMock()
        post_slack_update_mock = AsyncMock()
        read_sandbox_logs_mock = AsyncMock()
        cleanup_sandbox_mock = AsyncMock()
        create_resume_snapshot_mock = AsyncMock()

        monkeypatch.setattr(workflow, "_get_task_processing_context", get_task_processing_context_mock)
        monkeypatch.setattr(workflow, "_update_task_run_status", update_task_run_status_mock)
        monkeypatch.setattr(workflow, "_track_workflow_event", track_workflow_event_mock)
        monkeypatch.setattr(workflow, "_post_slack_update", post_slack_update_mock)
        monkeypatch.setattr(workflow, "_read_sandbox_logs", read_sandbox_logs_mock)
        monkeypatch.setattr(workflow, "_cleanup_sandbox", cleanup_sandbox_mock)
        monkeypatch.setattr(workflow, "_create_resume_snapshot", create_resume_snapshot_mock)
        monkeypatch.setattr(workflow, "_emit_progress", AsyncMock())

        async def fail_after_sandbox_creation() -> GetSandboxForRepositoryOutput:
            workflow._sandbox_id_for_cleanup = "sandbox-123"
            raise RuntimeError("clone failed")

        monkeypatch.setattr(workflow, "_get_sandbox_for_repository", fail_after_sandbox_creation)

        result = await workflow.run(ProcessTaskInput(run_id="run-id"))

        assert result.success is False
        assert result.error == "clone failed"
        assert result.sandbox_id == "sandbox-123"
        read_sandbox_logs_mock.assert_awaited_once_with("sandbox-123")
        cleanup_sandbox_mock.assert_awaited_once_with("sandbox-123")

    async def test_run_marks_failed_when_context_load_fails(self, monkeypatch):
        workflow = ProcessTaskWorkflow()
        get_task_processing_context_mock = AsyncMock(side_effect=RuntimeError("database connection closed"))
        update_task_run_status_mock = AsyncMock()
        track_workflow_event_mock = AsyncMock()
        post_slack_update_mock = AsyncMock()

        monkeypatch.setattr(workflow, "_get_task_processing_context", get_task_processing_context_mock)
        monkeypatch.setattr(workflow, "_update_task_run_status", update_task_run_status_mock)
        monkeypatch.setattr(workflow, "_track_workflow_event", track_workflow_event_mock)
        monkeypatch.setattr(workflow, "_post_slack_update", post_slack_update_mock)

        result = await workflow.run(ProcessTaskInput(run_id="run-id"))

        assert result.success is False
        assert result.error == "database connection closed"
        assert result.sandbox_id is None
        update_task_run_status_mock.assert_awaited_once_with(
            "failed",
            error_message="database connection closed",
            run_id="run-id",
        )
        track_workflow_event_mock.assert_not_awaited()
        post_slack_update_mock.assert_not_awaited()

    async def test_get_sandbox_for_repository_skips_clone_and_checkout_for_private_repo_without_github_integration(
        self, monkeypatch
    ):
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(github_integration_id=None)

        prepared = PrepareSandboxForRepositoryOutput(
            sandbox_name="sandbox-name",
            repository="posthog/charts",
            github_token="",
            branch="feature-branch",
            environment_variables={},
            snapshot_id=None,
            snapshot_external_id=None,
            used_snapshot=False,
            should_create_snapshot=True,
            shallow_clone=True,
            image_source="base_image",
            image_source_label="published sandbox base image",
        )
        created = CreateSandboxForRepositoryOutput(
            sandbox_id="sandbox-123",
            sandbox_url="https://sandbox.example",
            connect_token="connect-token",
        )
        activity_calls: list[object] = []

        async def fake_execute_activity(activity_fn, *args, **kwargs):
            activity_calls.append(activity_fn)
            if activity_fn is prepare_sandbox_for_repository:
                return prepared
            if activity_fn is create_sandbox_for_repository:
                return created
            if activity_fn is emit_progress_activity:
                return None
            raise AssertionError(f"Unexpected activity call: {activity_fn}")

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", fake_execute_activity)

        result = await workflow._get_sandbox_for_repository()

        assert result.sandbox_id == "sandbox-123"
        assert workflow._sandbox_id_for_cleanup == "sandbox-123"
        assert clone_repository_in_sandbox not in activity_calls
        assert checkout_branch_in_sandbox not in activity_calls

    async def test_get_sandbox_for_repository_injects_fresh_tokens_on_resume(self, monkeypatch):
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(
            github_integration_id=123,
            state={"snapshot_external_id": "im-abc123", "resume_from_run_id": "previous-run-id"},
        )

        prepared = PrepareSandboxForRepositoryOutput(
            sandbox_name="sandbox-name",
            repository="posthog/posthog-js",
            github_token="ghs_fresh",
            branch=None,
            environment_variables={},
            snapshot_id=None,
            snapshot_external_id="im-abc123",
            used_snapshot=True,
            should_create_snapshot=False,
            shallow_clone=True,
            image_source="resume_snapshot",
            image_source_label="resume snapshot im-abc123",
        )
        created = CreateSandboxForRepositoryOutput(
            sandbox_id="sandbox-123",
            sandbox_url="https://sandbox.example",
            connect_token="connect-token",
        )
        activity_calls: list[object] = []
        inject_call_args: dict = {}

        async def fake_execute_activity(activity_fn, *args, **kwargs):
            activity_calls.append(activity_fn)
            if activity_fn is prepare_sandbox_for_repository:
                return prepared
            if activity_fn is create_sandbox_for_repository:
                return created
            if activity_fn is inject_fresh_tokens_on_resume:
                inject_call_args["input"] = args[0]
                return None
            if activity_fn is emit_progress_activity:
                return None
            raise AssertionError(f"Unexpected activity call: {activity_fn}")

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", fake_execute_activity)

        result = await workflow._get_sandbox_for_repository()

        assert result.sandbox_id == "sandbox-123"
        assert inject_fresh_tokens_on_resume in activity_calls
        # Should run after create, before any clone/checkout
        assert activity_calls.index(inject_fresh_tokens_on_resume) > activity_calls.index(create_sandbox_for_repository)
        assert clone_repository_in_sandbox not in activity_calls
        assert checkout_branch_in_sandbox not in activity_calls
        assert inject_call_args["input"].sandbox_id == "sandbox-123"
        assert inject_call_args["input"].repository == "posthog/posthog-js"

    async def test_get_sandbox_for_repository_skips_token_injection_when_not_resuming(self, monkeypatch):
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(github_integration_id=123)

        prepared = PrepareSandboxForRepositoryOutput(
            sandbox_name="sandbox-name",
            repository="posthog/posthog-js",
            github_token="ghs_fresh",
            branch=None,
            environment_variables={},
            snapshot_id="repo-snapshot-id",
            snapshot_external_id=None,
            used_snapshot=True,
            should_create_snapshot=False,
            shallow_clone=True,
            image_source="repository_snapshot",
            image_source_label="repository snapshot x",
        )
        created = CreateSandboxForRepositoryOutput(
            sandbox_id="sandbox-123",
            sandbox_url="https://sandbox.example",
            connect_token="connect-token",
        )
        activity_calls: list[object] = []

        async def fake_execute_activity(activity_fn, *args, **kwargs):
            activity_calls.append(activity_fn)
            if activity_fn is prepare_sandbox_for_repository:
                return prepared
            if activity_fn is create_sandbox_for_repository:
                return created
            if activity_fn is emit_progress_activity:
                return None
            raise AssertionError(f"Unexpected activity call: {activity_fn}")

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", fake_execute_activity)

        await workflow._get_sandbox_for_repository()

        assert inject_fresh_tokens_on_resume not in activity_calls
