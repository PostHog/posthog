import os
import json
import uuid
import random
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from unittest.mock import AsyncMock, Mock

from django.conf import settings

from asgiref.sync import sync_to_async
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError, RetryState
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.tasks.backend.logic.services.sandbox import Sandbox, SandboxConfig, SandboxStatus, SandboxTemplate
from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.temporal.constants import INACTIVITY_TIMEOUT_USER_SECONDS, WARM_IDLE_TIMEOUT
from products.tasks.backend.temporal.process_task import workflow as process_task_workflow_module
from products.tasks.backend.temporal.process_task.activities import (
    CleanupSandboxInput,
    CreateSandboxForRepositoryInput,
    CreateSandboxForRepositoryOutput,
    GetSandboxForRepositoryOutput,
    InvalidateResumeSnapshotInput,
    PrepareSandboxForRepositoryOutput,
    StartAgentServerOutput,
    TaskProcessingContext,
    checkout_branch_in_sandbox,
    cleanup_sandbox,
    clone_repository_in_sandbox,
    create_sandbox_for_repository,
    emit_progress_activity,
    forward_pending_user_message,
    get_task_processing_context,
    inject_fresh_tokens_on_resume,
    invalidate_resume_snapshot,
    prepare_sandbox_for_repository,
    read_sandbox_logs,
    start_agent_server,
    track_workflow_event,
    update_task_run_status,
)
from products.tasks.backend.temporal.process_task.credential_refresh import (
    SANDBOX_GONE_ERROR_MESSAGE,
    CredentialRefreshExitReason,
)
from products.tasks.backend.temporal.process_task.workflow import (
    PendingFollowup,
    ProcessTaskInput,
    ProcessTaskOutput,
    ProcessTaskWorkflow,
)


def _build_context(
    *,
    github_integration_id: int | None,
    repository: str | None = "posthog/posthog-js",
    state: dict | None = None,
    use_modal_resume_snapshots: bool = True,
    sandbox_event_ingest_enabled: bool = False,
    environment: str | None = None,
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
        environment=environment,
        create_pr=True,
        state=state or {},
        _branch="feature-branch",
        use_modal_resume_snapshots=use_modal_resume_snapshots,
        sandbox_event_ingest_enabled=sandbox_event_ingest_enabled,
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
    async def test_send_followup_message_can_arrive_before_context_is_loaded(self, monkeypatch):
        logger = Mock()
        deprecate_patch = Mock()
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", logger)
        monkeypatch.setattr(process_task_workflow_module.workflow, "deprecate_patch", deprecate_patch)
        workflow = ProcessTaskWorkflow()

        await workflow.send_followup_message("first", ["artifact-1"])
        await workflow.send_followup_message("second", ["artifact-2"])

        assert workflow._pending_followups == [
            PendingFollowup(message="first", artifact_ids=["artifact-1"]),
            PendingFollowup(message="second", artifact_ids=["artifact-2"]),
        ]
        assert workflow._pending_followup is None
        deprecate_patch.assert_called_with(process_task_workflow_module._PATCH_ID_FOLLOWUP_QUEUE)
        logger.info.assert_any_call(
            "send_followup_signal_received",
            extra={
                "run_id": None,
                "message_length": 5,
                "artifact_count": 1,
            },
        )
        logger.info.assert_any_call(
            "send_followup_signal_received",
            extra={
                "run_id": None,
                "message_length": 6,
                "artifact_count": 1,
            },
        )
        assert logger.info.call_count == 2

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

    @pytest.mark.parametrize(
        "payload, expected_prewarmed",
        [
            ({"run_id": "r1"}, False),
            ({"run_id": "r1", "prewarmed": False}, False),
            ({"run_id": "r1", "prewarmed": True}, True),
        ],
    )
    def test_parse_inputs_reads_prewarmed(self, payload: dict, expected_prewarmed: bool):
        parsed = ProcessTaskWorkflow.parse_inputs([json.dumps(payload)])
        assert parsed.prewarmed is expected_prewarmed

    def test_warm_idle_timeout_is_shorter_than_active_inactivity(self):
        assert WARM_IDLE_TIMEOUT < timedelta(seconds=INACTIVITY_TIMEOUT_USER_SECONDS)

    async def test_credential_refresh_exit_marks_sandbox_gone(self, monkeypatch):
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(github_integration_id=123)
        logger = Mock()
        refresh_loop_mock = AsyncMock(return_value=CredentialRefreshExitReason.SANDBOX_GONE)

        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", logger)
        monkeypatch.setattr(process_task_workflow_module, "run_credential_refresh_loop", refresh_loop_mock)

        await workflow._run_credential_refresh_until_sandbox_gone("sandbox-123")

        assert workflow._sandbox_gone is True
        refresh_loop_mock.assert_awaited_once_with(workflow.context, "sandbox-123")
        logger.warning.assert_called_once_with(
            "sandbox_gone_detected",
            extra={"run_id": "run-id", "sandbox_id": "sandbox-123"},
        )

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

    async def test_run_refuses_local_environment_run_without_touching_it(self, monkeypatch):
        # If a local (desktop-driven) run is ever cloud-dispatched again (e.g. the reconciler's
        # environment filter regresses), the workflow must bail out without provisioning anything
        # and — critically — without flipping the live local session's status.
        workflow = ProcessTaskWorkflow()
        update_task_run_status_mock = AsyncMock()
        get_sandbox_mock = AsyncMock()

        monkeypatch.setattr(
            workflow,
            "_get_task_processing_context",
            AsyncMock(return_value=_build_context(github_integration_id=None, environment="local")),
        )
        monkeypatch.setattr(workflow, "_update_task_run_status", update_task_run_status_mock)
        monkeypatch.setattr(workflow, "_track_workflow_event", AsyncMock())
        monkeypatch.setattr(workflow, "_post_slack_update", AsyncMock())
        monkeypatch.setattr(workflow, "_emit_progress", AsyncMock())
        monkeypatch.setattr(workflow, "_get_sandbox_for_repository", get_sandbox_mock)
        monkeypatch.setattr(process_task_workflow_module.workflow, "patched", Mock(return_value=True))
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())

        result = await workflow.run(ProcessTaskInput(run_id="run-id"))

        assert result.success is False
        assert "local" in (result.error or "")
        update_task_run_status_mock.assert_not_awaited()
        get_sandbox_mock.assert_not_awaited()

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

    async def test_run_persists_activity_failure_cause_not_the_wrapper(self, monkeypatch):
        workflow = ProcessTaskWorkflow()
        error = ActivityError(
            "Activity task failed",
            scheduled_event_id=10,
            started_event_id=11,
            identity="worker-1",
            activity_type="inject_fresh_tokens_on_resume",
            activity_id="activity-1",
            retry_state=RetryState.MAXIMUM_ATTEMPTS_REACHED,
        )
        error.__cause__ = ApplicationError("Sandbox not in running state.", type="SandboxNotRunningError")
        update_task_run_status_mock = AsyncMock()

        monkeypatch.setattr(
            workflow, "_get_task_processing_context", AsyncMock(return_value=_build_context(github_integration_id=123))
        )
        monkeypatch.setattr(workflow, "_update_task_run_status", update_task_run_status_mock)
        monkeypatch.setattr(workflow, "_track_workflow_event", AsyncMock())
        monkeypatch.setattr(workflow, "_post_slack_update", AsyncMock())
        monkeypatch.setattr(workflow, "_emit_progress", AsyncMock())
        monkeypatch.setattr(workflow, "_get_sandbox_for_repository", AsyncMock(side_effect=error))

        result = await workflow.run(ProcessTaskInput(run_id="run-id"))

        assert result.success is False
        assert result.error == "Sandbox not in running state."
        update_task_run_status_mock.assert_awaited_with(
            "failed",
            error_message="Sandbox not in running state.",
            run_id="run-id",
        )

    async def test_run_skips_relay_when_sandbox_event_ingest_is_enabled(self, monkeypatch):
        workflow = ProcessTaskWorkflow()
        context = _build_context(github_integration_id=123, sandbox_event_ingest_enabled=True)
        get_task_processing_context_mock = AsyncMock(return_value=context)
        update_task_run_status_mock = AsyncMock()
        track_workflow_event_mock = AsyncMock()
        post_slack_update_mock = AsyncMock()
        read_sandbox_logs_mock = AsyncMock()
        cleanup_sandbox_mock = AsyncMock()
        create_resume_snapshot_mock = AsyncMock()
        relay_sandbox_events_mock = AsyncMock()

        monkeypatch.setattr(workflow, "_get_task_processing_context", get_task_processing_context_mock)
        monkeypatch.setattr(workflow, "_update_task_run_status", update_task_run_status_mock)
        monkeypatch.setattr(workflow, "_track_workflow_event", track_workflow_event_mock)
        monkeypatch.setattr(workflow, "_post_slack_update", post_slack_update_mock)
        monkeypatch.setattr(workflow, "_read_sandbox_logs", read_sandbox_logs_mock)
        monkeypatch.setattr(workflow, "_cleanup_sandbox", cleanup_sandbox_mock)
        monkeypatch.setattr(workflow, "_create_resume_snapshot", create_resume_snapshot_mock)
        monkeypatch.setattr(workflow, "_emit_progress", AsyncMock())
        monkeypatch.setattr(workflow, "_forward_pending_user_message", AsyncMock())
        monkeypatch.setattr(
            workflow,
            "_get_sandbox_for_repository",
            AsyncMock(
                return_value=GetSandboxForRepositoryOutput(
                    sandbox_id="sandbox-123",
                    sandbox_url="https://sandbox.example",
                    connect_token="connect-token",
                    used_snapshot=False,
                    should_create_snapshot=False,
                )
            ),
        )
        monkeypatch.setattr(
            workflow,
            "_start_agent_server",
            AsyncMock(
                return_value=StartAgentServerOutput(
                    sandbox_url="https://sandbox.example",
                    connect_token="connect-token",
                )
            ),
        )
        monkeypatch.setattr(
            workflow, "_wait_for_event", AsyncMock(return_value=process_task_workflow_module.TaskEvent.TIMEOUT_REACHED)
        )
        monkeypatch.setattr(workflow, "_relay_sandbox_events", relay_sandbox_events_mock)
        monkeypatch.setattr(process_task_workflow_module.workflow, "patched", Mock(return_value=True))

        result = await workflow.run(ProcessTaskInput(run_id="run-id"))

        assert result.success is True
        relay_sandbox_events_mock.assert_not_awaited()

    async def test_run_relays_agent_design_signals_when_ingest_and_agent_design_enabled(self, monkeypatch):
        workflow = ProcessTaskWorkflow()
        context = _build_context(github_integration_id=123, sandbox_event_ingest_enabled=True)
        relay_sandbox_events_mock = AsyncMock()
        relay_agent_design_signals_mock = AsyncMock()

        monkeypatch.setattr(workflow, "_get_task_processing_context", AsyncMock(return_value=context))
        monkeypatch.setattr(workflow, "_update_task_run_status", AsyncMock())
        monkeypatch.setattr(workflow, "_track_workflow_event", AsyncMock())
        monkeypatch.setattr(workflow, "_post_slack_update", AsyncMock())
        monkeypatch.setattr(workflow, "_read_sandbox_logs", AsyncMock())
        monkeypatch.setattr(workflow, "_cleanup_sandbox", AsyncMock())
        monkeypatch.setattr(workflow, "_create_resume_snapshot", AsyncMock())
        monkeypatch.setattr(workflow, "_emit_progress", AsyncMock())
        monkeypatch.setattr(workflow, "_forward_pending_user_message", AsyncMock())
        monkeypatch.setattr(workflow, "_resolve_agent_design_flag", AsyncMock(return_value=True))
        monkeypatch.setattr(
            workflow,
            "_get_sandbox_for_repository",
            AsyncMock(
                return_value=GetSandboxForRepositoryOutput(
                    sandbox_id="sandbox-123",
                    sandbox_url="https://sandbox.example",
                    connect_token="connect-token",
                    used_snapshot=False,
                    should_create_snapshot=False,
                )
            ),
        )
        monkeypatch.setattr(
            workflow,
            "_start_agent_server",
            AsyncMock(
                return_value=StartAgentServerOutput(
                    sandbox_url="https://sandbox.example",
                    connect_token="connect-token",
                )
            ),
        )
        monkeypatch.setattr(
            workflow, "_wait_for_event", AsyncMock(return_value=process_task_workflow_module.TaskEvent.TIMEOUT_REACHED)
        )
        monkeypatch.setattr(workflow, "_relay_sandbox_events", relay_sandbox_events_mock)
        monkeypatch.setattr(workflow, "_relay_agent_design_signals", relay_agent_design_signals_mock)
        monkeypatch.setattr(process_task_workflow_module.workflow, "patched", Mock(return_value=True))

        result = await workflow.run(ProcessTaskInput(run_id="run-id", slack_thread_context={"channel": "C1"}))

        assert result.success is True
        relay_sandbox_events_mock.assert_not_called()
        relay_agent_design_signals_mock.assert_called_once()

    async def test_run_completes_when_credential_refresh_detects_sandbox_gone(self, monkeypatch):
        workflow = ProcessTaskWorkflow()
        context = _build_context(github_integration_id=123)
        update_task_run_status_mock = AsyncMock()
        cleanup_sandbox_mock = AsyncMock()

        monkeypatch.setattr(workflow, "_get_task_processing_context", AsyncMock(return_value=context))
        monkeypatch.setattr(workflow, "_update_task_run_status", update_task_run_status_mock)
        monkeypatch.setattr(workflow, "_track_workflow_event", AsyncMock())
        monkeypatch.setattr(workflow, "_post_slack_update", AsyncMock())
        monkeypatch.setattr(workflow, "_read_sandbox_logs", AsyncMock())
        monkeypatch.setattr(workflow, "_cleanup_sandbox", cleanup_sandbox_mock)
        monkeypatch.setattr(workflow, "_create_resume_snapshot", AsyncMock())
        monkeypatch.setattr(workflow, "_emit_progress", AsyncMock())
        monkeypatch.setattr(workflow, "_forward_pending_user_message", AsyncMock())
        monkeypatch.setattr(
            workflow,
            "_get_sandbox_for_repository",
            AsyncMock(
                return_value=GetSandboxForRepositoryOutput(
                    sandbox_id="sandbox-123",
                    sandbox_url="https://sandbox.example",
                    connect_token="connect-token",
                    used_snapshot=False,
                    should_create_snapshot=False,
                )
            ),
        )
        monkeypatch.setattr(
            workflow,
            "_start_agent_server",
            AsyncMock(
                return_value=StartAgentServerOutput(
                    sandbox_url="https://sandbox.example",
                    connect_token="connect-token",
                )
            ),
        )
        monkeypatch.setattr(workflow, "_relay_sandbox_events", AsyncMock())
        monkeypatch.setattr(workflow, "_run_credential_refresh_until_sandbox_gone", AsyncMock())
        monkeypatch.setattr(
            workflow, "_wait_for_event", AsyncMock(return_value=process_task_workflow_module.TaskEvent.SANDBOX_GONE)
        )
        monkeypatch.setattr(process_task_workflow_module.workflow, "patched", Mock(return_value=True))

        result = await workflow.run(ProcessTaskInput(run_id="run-id"))

        assert result.success is True
        assert workflow._completion_status == "completed"
        update_task_run_status_mock.assert_any_await(
            "completed",
            error_message=SANDBOX_GONE_ERROR_MESSAGE,
        )
        cleanup_sandbox_mock.assert_awaited_once_with("sandbox-123")

    @pytest.mark.parametrize(
        "patched, expected_post_slack_calls",
        [
            (True, 2),  # post-rollout: the provisioning post is skipped (initial + completion remain)
            (False, 3),  # pre-rollout replay: provisioning post is still scheduled to match history
        ],
    )
    async def test_run_gates_slack_post_after_provisioning_on_patch(
        self, monkeypatch, patched, expected_post_slack_calls
    ):
        workflow = ProcessTaskWorkflow()
        post_slack_update_mock = AsyncMock()

        monkeypatch.setattr(
            workflow, "_get_task_processing_context", AsyncMock(return_value=_build_context(github_integration_id=123))
        )
        monkeypatch.setattr(workflow, "_update_task_run_status", AsyncMock())
        monkeypatch.setattr(workflow, "_track_workflow_event", AsyncMock())
        monkeypatch.setattr(workflow, "_post_slack_update", post_slack_update_mock)
        monkeypatch.setattr(workflow, "_emit_progress", AsyncMock())
        monkeypatch.setattr(workflow, "_read_sandbox_logs", AsyncMock())
        monkeypatch.setattr(workflow, "_cleanup_sandbox", AsyncMock())
        monkeypatch.setattr(workflow, "_create_resume_snapshot", AsyncMock())
        monkeypatch.setattr(workflow, "_forward_pending_user_message", AsyncMock())
        monkeypatch.setattr(
            workflow,
            "_get_sandbox_for_repository",
            AsyncMock(
                return_value=GetSandboxForRepositoryOutput(
                    sandbox_id="sandbox-123",
                    sandbox_url="https://sandbox.example",
                    connect_token="connect-token",
                    used_snapshot=False,
                    should_create_snapshot=False,
                )
            ),
        )
        monkeypatch.setattr(
            workflow,
            "_start_agent_server",
            AsyncMock(
                return_value=StartAgentServerOutput(
                    sandbox_url="https://sandbox.example",
                    connect_token="connect-token",
                )
            ),
        )
        monkeypatch.setattr(
            workflow, "_wait_for_event", AsyncMock(return_value=process_task_workflow_module.TaskEvent.TIMEOUT_REACHED)
        )
        monkeypatch.setattr(workflow, "_relay_sandbox_events", AsyncMock())
        monkeypatch.setattr(process_task_workflow_module.workflow, "patched", Mock(return_value=patched))

        result = await workflow.run(ProcessTaskInput(run_id="run-id"))

        assert result.success is True
        assert post_slack_update_mock.await_count == expected_post_slack_calls

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

    async def test_get_sandbox_for_repository_falls_back_to_fresh_sandbox_when_resume_injection_fails(
        self, monkeypatch
    ):
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
        created_dead = CreateSandboxForRepositoryOutput(
            sandbox_id="sandbox-dead",
            sandbox_url="https://sandbox.example",
            connect_token="connect-token",
        )
        created_fresh = CreateSandboxForRepositoryOutput(
            sandbox_id="sandbox-fresh",
            sandbox_url="https://sandbox.example",
            connect_token="connect-token",
        )
        activity_calls: list[object] = []
        create_inputs: list[CreateSandboxForRepositoryInput] = []
        invalidate_inputs: list[InvalidateResumeSnapshotInput] = []
        cleanup_inputs: list[CleanupSandboxInput] = []

        async def fake_execute_activity(activity_fn, *args, **kwargs):
            activity_calls.append(activity_fn)
            if activity_fn is prepare_sandbox_for_repository:
                return prepared
            if activity_fn is create_sandbox_for_repository:
                create_inputs.append(args[0])
                return created_dead if len(create_inputs) == 1 else created_fresh
            if activity_fn is inject_fresh_tokens_on_resume:
                raise ApplicationError("Sandbox not in running state.", type="SandboxNotRunningError")
            if activity_fn is invalidate_resume_snapshot:
                invalidate_inputs.append(args[0])
                return None
            if activity_fn is cleanup_sandbox:
                cleanup_inputs.append(args[0])
                return None
            if activity_fn in (clone_repository_in_sandbox, emit_progress_activity):
                return None
            raise AssertionError(f"Unexpected activity call: {activity_fn}")

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", fake_execute_activity)
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())

        result = await workflow._get_sandbox_for_repository()

        assert result.sandbox_id == "sandbox-fresh"
        assert result.used_snapshot is False
        assert [i.run_id for i in invalidate_inputs] == ["run-id"]
        assert [i.sandbox_id for i in cleanup_inputs] == ["sandbox-dead"]
        assert len(create_inputs) == 2
        fresh_prepared = create_inputs[1].prepared
        assert fresh_prepared.snapshot_external_id is None
        assert fresh_prepared.used_snapshot is False
        assert fresh_prepared.should_create_snapshot is True
        assert clone_repository_in_sandbox in activity_calls

    async def test_get_sandbox_for_repository_propagates_non_dead_sandbox_failures(self, monkeypatch):
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
            sandbox_id="sandbox-live",
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
            if activity_fn is inject_fresh_tokens_on_resume:
                raise ApplicationError("Failed to refresh GitHub token", type="GitHubAuthenticationError")
            if activity_fn is emit_progress_activity:
                return None
            raise AssertionError(f"Unexpected activity call: {activity_fn}")

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", fake_execute_activity)

        with pytest.raises(ApplicationError, match="Failed to refresh GitHub token"):
            await workflow._get_sandbox_for_repository()

        assert invalidate_resume_snapshot not in activity_calls
        assert cleanup_sandbox not in activity_calls

    @pytest.mark.parametrize(
        "mode, use_modal_resume_snapshots, expect_resume_snapshot_call",
        [
            ("interactive", True, True),
            ("interactive", False, False),
            ("background", True, False),
        ],
    )
    async def test_finally_block_creates_resume_snapshot_for_interactive_runs(
        self, monkeypatch, mode, use_modal_resume_snapshots, expect_resume_snapshot_call
    ):
        workflow = ProcessTaskWorkflow()
        get_task_processing_context_mock = AsyncMock(
            return_value=_build_context(
                github_integration_id=123,
                state={"mode": mode},
                use_modal_resume_snapshots=use_modal_resume_snapshots,
            )
        )
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

        # Force the workflow into the finally block with a sandbox to clean up.
        async def fail_after_sandbox_creation() -> GetSandboxForRepositoryOutput:
            workflow._sandbox_id_for_cleanup = "sandbox-123"
            raise RuntimeError("forced failure to reach finally block")

        monkeypatch.setattr(workflow, "_get_sandbox_for_repository", fail_after_sandbox_creation)

        await workflow.run(ProcessTaskInput(run_id="run-id"))

        cleanup_sandbox_mock.assert_awaited_once_with("sandbox-123")
        if expect_resume_snapshot_call:
            create_resume_snapshot_mock.assert_awaited_once_with("sandbox-123")
        else:
            create_resume_snapshot_mock.assert_not_awaited()

    @pytest.mark.parametrize(
        "use_modal_resume_snapshots",
        [
            True,
            False,
        ],
    )
    async def test_get_sandbox_uses_stored_snapshot_regardless_of_legacy_modal_resume_flag(
        self,
        monkeypatch,
        use_modal_resume_snapshots,
    ):
        """Stored snapshot IDs are restored even if the legacy context field is false."""
        prior_snapshot_external_id = "im-abc123"

        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(
            github_integration_id=123,
            state={"snapshot_external_id": prior_snapshot_external_id, "resume_from_run_id": "previous-run-id"},
            use_modal_resume_snapshots=use_modal_resume_snapshots,
        )

        # Mirror what `prepare_sandbox_for_repository` produces from stored snapshot state.
        prepared = PrepareSandboxForRepositoryOutput(
            sandbox_name="sandbox-name",
            repository="posthog/posthog-js",
            github_token="ghs_fresh",
            branch=None,
            environment_variables={},
            snapshot_id=None,
            snapshot_external_id=prior_snapshot_external_id,
            used_snapshot=True,
            should_create_snapshot=False,
            shallow_clone=True,
            image_source="resume_snapshot",
            image_source_label="resume snapshot",
        )
        created = CreateSandboxForRepositoryOutput(
            sandbox_id="sandbox-123",
            sandbox_url="https://sandbox.example",
            connect_token="connect-token",
            used_snapshot=True,
        )
        activity_calls: list[object] = []

        async def fake_execute_activity(activity_fn, *args, **kwargs):
            activity_calls.append(activity_fn)
            if activity_fn is prepare_sandbox_for_repository:
                return prepared
            if activity_fn is create_sandbox_for_repository:
                return created
            if activity_fn is inject_fresh_tokens_on_resume:
                return None
            if activity_fn is emit_progress_activity:
                return None
            if activity_fn is clone_repository_in_sandbox:
                return None
            if activity_fn is checkout_branch_in_sandbox:
                return None
            raise AssertionError(f"Unexpected activity call: {activity_fn}")

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", fake_execute_activity)

        await workflow._get_sandbox_for_repository()

        assert inject_fresh_tokens_on_resume in activity_calls
