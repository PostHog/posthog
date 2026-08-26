import os
import json
import uuid
import random
import asyncio
import dataclasses
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from unittest.mock import AsyncMock, Mock

from django.conf import settings

from asgiref.sync import sync_to_async
from parameterized import parameterized
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError, RetryState
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.tasks.backend.logic.services.sandbox import Sandbox, SandboxConfig, SandboxStatus, SandboxTemplate
from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.temporal.babysit_pr.snapshot import BabysitJournal
from products.tasks.backend.temporal.constants import (
    INACTIVITY_TIMEOUT_USER_SECONDS,
    SANDBOX_TTL_SNAPSHOT_LEAD,
    WARM_IDLE_TIMEOUT,
)
from products.tasks.backend.temporal.process_task import workflow as process_task_workflow_module
from products.tasks.backend.temporal.process_task.activities import (
    STEER_DECLINED_OUTCOME,
    CleanupSandboxInput,
    CompleteRunStreamInput,
    CreateSandboxForRepositoryInput,
    CreateSandboxForRepositoryOutput,
    GetSandboxForRepositoryOutput,
    InvalidateResumeSnapshotInput,
    PrepareSandboxForRepositoryOutput,
    SendPermissionDenialGuidanceInput,
    SendPermissionResponseToSandboxInput,
    StartAgentServerOutput,
    TaskProcessingContext,
    checkout_branch_in_sandbox,
    cleanup_sandbox,
    clone_repository_in_sandbox,
    complete_run_stream,
    create_sandbox_for_repository,
    emit_progress_activity,
    forward_pending_user_message,
    get_task_processing_context,
    inject_fresh_tokens_on_resume,
    invalidate_resume_snapshot,
    launch_agent_server,
    mark_repo_ready,
    post_permission_delivery_failure_notice,
    prepare_sandbox_for_repository,
    read_sandbox_logs,
    send_permission_denial_guidance,
    send_permission_response_to_sandbox,
    start_agent_server,
    track_workflow_event,
    update_task_run_status,
)
from products.tasks.backend.temporal.process_task.activities.create_resume_snapshot import CreateResumeSnapshotOutput
from products.tasks.backend.temporal.process_task.activities.emit_progress_activity import EmitProgressInput
from products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox import SendFollowupToSandboxInput
from products.tasks.backend.temporal.process_task.activities.update_task_run_status import (
    SANDBOX_GONE_STATE_KEY,
    TIMED_OUT_WALL_CLOCK_STATE_KEY,
)
from products.tasks.backend.temporal.process_task.credential_refresh import (
    SANDBOX_GONE_ERROR_MESSAGE,
    CredentialRefreshExitReason,
)
from products.tasks.backend.temporal.process_task.workflow import (
    PendingFollowup,
    PendingPermissionResponse,
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
    use_modal_vm_sandbox: bool = False,
    custom_image_name: str | None = None,
    origin_product: str | None = None,
    create_pr: bool = True,
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
        origin_product=origin_product,
        environment=environment,
        create_pr=create_pr,
        state=state or {},
        _branch="feature-branch",
        use_modal_resume_snapshots=use_modal_resume_snapshots,
        sandbox_event_ingest_enabled=sandbox_event_ingest_enabled,
        use_modal_vm_sandbox=use_modal_vm_sandbox,
        custom_image_name=custom_image_name,
    )


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


def test_activity_error_properties_names_the_application_failure_class():
    error = ActivityError(
        "Activity task failed",
        scheduled_event_id=10,
        started_event_id=11,
        identity="worker-1",
        activity_type="create_sandbox_for_repository",
        activity_id="activity-1",
        retry_state=RetryState.NON_RETRYABLE_FAILURE,
    )
    error.__cause__ = ApplicationError("Failed to create sandbox", type="SandboxProvisionError")

    properties = ProcessTaskWorkflow._activity_error_properties(error)

    assert properties["cause_error_type"] == "SandboxProvisionError"


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
                    complete_run_stream,
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
                    complete_run_stream,
                    track_workflow_event,
                    update_task_run_status,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=10),
            ),
        ):
            # The run row does not exist, so the terminal status write raises
            # TaskRunDeletedError and the workflow fails rather than returning a result. A
            # workflow with no row left to update has nowhere to record an outcome, so
            # failing is the only way its end is visible.
            with pytest.raises(WorkflowFailureError) as failure:
                await env.client.execute_workflow(
                    ProcessTaskWorkflow.run,
                    workflow_input,
                    id=workflow_id,
                    task_queue=settings.TASKS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=timedelta(minutes=60),
                )

        # `WorkflowFailureError` carries only a generic message; the reason is in the cause
        # chain, so assert there rather than on `str(failure.value)`.
        causes = []
        error: BaseException | None = failure.value
        while error is not None:
            causes.append(str(error))
            error = error.__cause__
        assert any("no longer exists" in cause or "not found" in cause for cause in causes), causes


class TestSandboxDeadline:
    """The provider kills a sandbox on a fixed clock. An interactive run has to snapshot
    itself before that lands, because the teardown snapshot runs against a sandbox that is
    already gone."""

    def _workflow(
        self,
        *,
        deadline: datetime | None,
        mode: str = "interactive",
        use_modal_resume_snapshots: bool = True,
    ) -> ProcessTaskWorkflow:
        wf = ProcessTaskWorkflow()
        wf._context = _build_context(
            github_integration_id=123,
            state={"mode": mode},
            use_modal_resume_snapshots=use_modal_resume_snapshots,
        )
        wf._sandbox_ttl_expires_at = deadline
        return wf

    def test_deadline_from_a_pre_rollout_history_leaves_the_timer_unscheduled(self):
        wf = self._workflow(deadline=None)
        created = CreateSandboxForRepositoryOutput(sandbox_id="sb-1", sandbox_url="https://s", connect_token=None)

        wf._record_sandbox_deadline(created)

        assert wf._sandbox_ttl_expires_at is None
        assert wf._sandbox_deadline_snapshot_scheduled() is False

    def test_a_replacement_sandbox_starts_its_clock_over(self, monkeypatch):
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())
        wf = self._workflow(deadline=datetime(2026, 7, 16, 12, 0, tzinfo=UTC))
        wf._sandbox_ttl_snapshot_taken = True

        wf._record_sandbox_deadline(
            CreateSandboxForRepositoryOutput(
                sandbox_id="sb-2",
                sandbox_url="https://s",
                connect_token=None,
                ttl_expires_at="2026-07-16T18:00:00+00:00",
            )
        )

        assert wf._sandbox_ttl_expires_at == datetime(2026, 7, 16, 18, 0, tzinfo=UTC)
        assert wf._sandbox_ttl_snapshot_taken is False
        assert wf._sandbox_deadline_snapshot_scheduled() is True

    @parameterized.expand(
        [
            ("already_snapshotted", {"snapshot_taken": True}, False),
            ("non_interactive", {"mode": "one_off"}, False),
            ("resume_snapshots_disabled", {"use_modal_resume_snapshots": False}, False),
            ("interactive_with_snapshots", {}, True),
        ]
    )
    def test_only_runs_with_something_to_restore_wait_on_the_deadline(self, _name, overrides, expected):
        wf = self._workflow(
            deadline=datetime(2026, 7, 16, 12, 0, tzinfo=UTC),
            mode=overrides.get("mode", "interactive"),
            use_modal_resume_snapshots=overrides.get("use_modal_resume_snapshots", True),
        )
        wf._sandbox_ttl_snapshot_taken = overrides.get("snapshot_taken", False)

        assert wf._sandbox_deadline_snapshot_scheduled() is expected

    async def test_timer_sleeps_until_the_lead_time_before_the_deadline(self, monkeypatch):
        wf = self._workflow(deadline=datetime(2026, 7, 16, 12, 0, tzinfo=UTC))
        sleep_mock = AsyncMock()
        monkeypatch.setattr(
            process_task_workflow_module.workflow, "now", Mock(return_value=datetime(2026, 7, 16, 9, 0, tzinfo=UTC))
        )
        monkeypatch.setattr(process_task_workflow_module.workflow, "sleep", sleep_mock)

        event = await wf._wait_for_sandbox_deadline()

        assert event == process_task_workflow_module.TaskEvent.SANDBOX_TTL_APPROACHING
        expected = (timedelta(hours=3) - SANDBOX_TTL_SNAPSHOT_LEAD).total_seconds()
        sleep_mock.assert_awaited_once_with(expected)

    async def test_a_deadline_already_inside_the_lead_time_fires_without_sleeping(self, monkeypatch):
        wf = self._workflow(deadline=datetime(2026, 7, 16, 12, 0, tzinfo=UTC))
        sleep_mock = AsyncMock()
        monkeypatch.setattr(
            process_task_workflow_module.workflow, "now", Mock(return_value=datetime(2026, 7, 16, 11, 55, tzinfo=UTC))
        )
        monkeypatch.setattr(process_task_workflow_module.workflow, "sleep", sleep_mock)

        event = await wf._wait_for_sandbox_deadline()

        assert event == process_task_workflow_module.TaskEvent.SANDBOX_TTL_APPROACHING
        sleep_mock.assert_not_awaited()


class TestSandboxRotation:
    """Rotation moves a run onto a replacement sandbox before the provider kills the one it has.
    Anything that goes wrong has to leave the run on its current sandbox, which still has the
    lead time left on its clock."""

    def _workflow(self, monkeypatch, *, rotation_enabled: bool = True) -> ProcessTaskWorkflow:
        wf = ProcessTaskWorkflow()
        wf._context = _build_context(github_integration_id=123, state={"mode": "interactive"})
        wf._context.sandbox_rotation_enabled = rotation_enabled
        wf._sandbox_url = "https://old.example"
        wf._sandbox_connect_token = "old-token"
        wf._sandbox_jwt_kid = "kid-old"
        wf._sandbox_id_for_cleanup = "sb-old"
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())
        return wf

    def _relay(self, name: str) -> "asyncio.Task[None]":
        return cast("asyncio.Task[None]", name)

    def _snapshot(self, external_id: str | None = "snap-1") -> CreateResumeSnapshotOutput:
        return CreateResumeSnapshotOutput(
            external_id=external_id, snapshot_kind="directory", snapshot_mount_path="/mnt/work"
        )

    def _replacement(self, used_snapshot: bool = True) -> GetSandboxForRepositoryOutput:
        return GetSandboxForRepositoryOutput(
            sandbox_id="sb-new",
            sandbox_url="https://new.example",
            connect_token="new-token",
            used_snapshot=used_snapshot,
            should_create_snapshot=not used_snapshot,
        )

    @parameterized.expand(
        [
            ("idle_with_flag_on", {}, True),
            ("flag_off", {"rotation_enabled": False}, False),
            ("agent_mid_turn", {"agent_active": True}, False),
            ("run_finishing", {"task_completed": True}, False),
            ("followup_in_flight", {"followup_running": True}, False),
            ("followup_finished", {"followup_running": False, "followup_present": True}, True),
        ]
    )
    def test_only_an_idle_run_with_the_flag_on_may_rotate(self, _name, overrides, expected):
        wf = ProcessTaskWorkflow()
        wf._context = _build_context(github_integration_id=123, state={"mode": "interactive"})
        wf._context.sandbox_rotation_enabled = overrides.get("rotation_enabled", True)
        wf._agent_active = overrides.get("agent_active", False)
        wf._task_completed = overrides.get("task_completed", False)
        if overrides.get("followup_running") or overrides.get("followup_present"):
            followup = Mock()
            followup.done.return_value = not overrides.get("followup_running", False)
            wf._active_followup_task = followup

        assert (wf._sandbox_rotation_block_reason() is None) is expected

    async def test_the_credential_refresh_loop_follows_the_run_to_the_new_sandbox(self, monkeypatch):
        wf = self._workflow(monkeypatch)
        monkeypatch.setattr(wf, "_create_resume_snapshot_output", AsyncMock(return_value=self._snapshot()))
        monkeypatch.setattr(wf, "_get_sandbox_for_repository", AsyncMock(return_value=self._replacement()))
        monkeypatch.setattr(wf, "_start_agent_server", AsyncMock())
        cancelled: list[object] = []
        monkeypatch.setattr(wf, "_cancel_relay", AsyncMock(side_effect=lambda task: cancelled.append(task)))
        monkeypatch.setattr(wf, "_cleanup_sandbox", AsyncMock())
        monkeypatch.setattr(wf, "_spawn_event_relay", Mock(return_value=None))
        spawn_refresh = Mock(return_value=self._relay("refresh-new"))
        monkeypatch.setattr(wf, "_spawn_credential_refresh", spawn_refresh)
        refresh_old = self._relay("refresh-old")

        await wf._rotate_sandbox_before_deadline("sb-old", None, refresh_old)

        assert refresh_old in cancelled
        spawn_refresh.assert_called_once_with("sb-new")

    async def test_successful_rotation_repoints_the_run_and_drops_the_old_sandbox(self, monkeypatch):
        wf = self._workflow(monkeypatch)
        monkeypatch.setattr(wf, "_create_resume_snapshot_output", AsyncMock(return_value=self._snapshot()))
        resume_flags_at_provision = {}

        async def provision_replacement():
            state = wf.context.state or {}
            resume_flags_at_provision["value"] = (state.get("handoff_resumed"), state.get("handoff_resume_idle"))
            return self._replacement()

        monkeypatch.setattr(wf, "_get_sandbox_for_repository", provision_replacement)
        monkeypatch.setattr(wf, "_start_agent_server", AsyncMock())
        monkeypatch.setattr(wf, "_cancel_relay", AsyncMock())
        cleanup = AsyncMock()
        monkeypatch.setattr(wf, "_cleanup_sandbox", cleanup)
        relay_new = self._relay("relay-new")
        refresh_new = self._relay("refresh-new")
        monkeypatch.setattr(wf, "_spawn_event_relay", Mock(return_value=relay_new))
        monkeypatch.setattr(wf, "_spawn_credential_refresh", Mock(return_value=refresh_new))

        rotation = await wf._rotate_sandbox_before_deadline(
            "sb-old", self._relay("relay-old"), self._relay("refresh-old")
        )

        assert rotation.sandbox_id == "sb-new"
        assert rotation.relay_task is relay_new
        assert rotation.credential_refresh_task is refresh_new
        assert (wf._sandbox_url, wf._sandbox_connect_token) == ("https://new.example", "new-token")
        assert wf._sandbox_id_for_cleanup == "sb-new"
        assert resume_flags_at_provision["value"] == (True, True)
        cleanup.assert_awaited_once_with("sb-old", complete_stream=False)

    async def test_the_replacement_is_built_from_the_snapshot_just_taken(self, monkeypatch):
        wf = self._workflow(monkeypatch)
        monkeypatch.setattr(wf, "_create_resume_snapshot_output", AsyncMock(return_value=self._snapshot()))
        monkeypatch.setattr(wf, "_get_sandbox_for_repository", AsyncMock(return_value=self._replacement()))
        monkeypatch.setattr(wf, "_start_agent_server", AsyncMock())
        monkeypatch.setattr(wf, "_cancel_relay", AsyncMock())
        monkeypatch.setattr(wf, "_cleanup_sandbox", AsyncMock())
        monkeypatch.setattr(wf, "_spawn_event_relay", Mock(return_value=None))
        monkeypatch.setattr(wf, "_spawn_credential_refresh", Mock(return_value=None))

        await wf._rotate_sandbox_before_deadline("sb-old", None, None)

        state = wf.context.state or {}
        assert state["snapshot_external_id"] == "snap-1"
        assert state["snapshot_kind"] == "directory"
        assert state["snapshot_mount_path"] == "/mnt/work"

    async def test_routing_that_could_not_be_restored_is_reported_not_swallowed(self, monkeypatch):
        wf = self._workflow(monkeypatch)
        monkeypatch.setattr(wf, "_create_resume_snapshot_output", AsyncMock(return_value=self._snapshot()))

        async def fail_after_creating() -> GetSandboxForRepositoryOutput:
            wf._sandbox_id_for_cleanup = "sb-half-built"
            raise RuntimeError("agent server never came up")

        monkeypatch.setattr(wf, "_get_sandbox_for_repository", fail_after_creating)
        monkeypatch.setattr(wf, "_cancel_relay", AsyncMock())
        monkeypatch.setattr(wf, "_cleanup_sandbox", AsyncMock())
        monkeypatch.setattr(wf, "_spawn_event_relay", Mock(return_value=None))
        monkeypatch.setattr(wf, "_spawn_credential_refresh", Mock(return_value=None))
        monkeypatch.setattr(wf, "_restore_sandbox_connection_state", AsyncMock(return_value=False))

        rotation = await wf._rotate_sandbox_before_deadline("sb-old", None, None)

        assert rotation.sandbox_id is None
        assert rotation.routing_restored is False

    async def test_a_replacement_built_without_the_snapshot_does_not_replace_the_live_sandbox(self, monkeypatch):
        # Provisioning reports success for a sandbox it had to build fresh, which holds the
        # branch head rather than the run's working tree. Completing the rotation there would
        # destroy the only copy of the agent's uncommitted work.
        wf = self._workflow(monkeypatch)
        monkeypatch.setattr(wf, "_create_resume_snapshot_output", AsyncMock(return_value=self._snapshot()))
        monkeypatch.setattr(
            wf, "_get_sandbox_for_repository", AsyncMock(return_value=self._replacement(used_snapshot=False))
        )
        monkeypatch.setattr(wf, "_start_agent_server", AsyncMock())
        monkeypatch.setattr(wf, "_cancel_relay", AsyncMock())
        cleanup = AsyncMock()
        monkeypatch.setattr(wf, "_cleanup_sandbox", cleanup)
        monkeypatch.setattr(wf, "_spawn_event_relay", Mock(return_value=None))
        monkeypatch.setattr(wf, "_spawn_credential_refresh", Mock(return_value=None))
        restore = AsyncMock(return_value=True)
        monkeypatch.setattr(wf, "_restore_sandbox_connection_state", restore)
        wf._sandbox_id_for_cleanup = "sb-new"

        rotation = await wf._rotate_sandbox_before_deadline("sb-old", None, None)

        assert rotation.sandbox_id is None
        assert (wf._sandbox_url, wf._sandbox_connect_token) == ("https://old.example", "old-token")
        assert wf._sandbox_id_for_cleanup == "sb-old"
        cleanup.assert_awaited_once_with("sb-new", complete_stream=False)
        restore.assert_awaited_once_with("sb-old", "https://old.example", "old-token", "kid-old")

    async def test_initial_provisioning_remembers_the_signing_key_of_the_sandbox_it_created(self, monkeypatch):
        wf = self._workflow(monkeypatch)
        wf._sandbox_jwt_kid = None
        prepared = PrepareSandboxForRepositoryOutput(
            sandbox_name="sandbox-name",
            repository="posthog/posthog-js",
            github_token="",
            branch=None,
            environment_variables={},
            snapshot_id=None,
            snapshot_external_id=None,
            used_snapshot=True,
            should_create_snapshot=False,
            shallow_clone=False,
            image_source="base_image",
            image_source_label="published sandbox base image",
            sandbox_creation_timeout_seconds=30 * 60,
        )
        created = CreateSandboxForRepositoryOutput(
            sandbox_id="sb-provisioned",
            sandbox_url="https://provisioned.example",
            connect_token="provisioned-token",
            used_snapshot=True,
            jwt_kid="kid-provisioned",
        )
        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", AsyncMock(return_value=prepared))
        monkeypatch.setattr(wf, "_run_sandbox_creation_activity", AsyncMock(return_value=created))
        monkeypatch.setattr(wf, "_record_sandbox_deadline", Mock())
        monkeypatch.setattr(wf, "_emit_progress", AsyncMock())

        output = await wf._get_sandbox_for_repository()

        assert output.jwt_kid == "kid-provisioned"
        assert wf._sandbox_jwt_kid == "kid-provisioned"

    @pytest.mark.parametrize(
        "snapshot_invalidated, expected_saved",
        [(False, True), (True, False)],
    )
    async def test_an_abandoned_rotation_reports_the_snapshot_it_already_took(
        self, monkeypatch, snapshot_invalidated, expected_saved
    ):
        wf = self._workflow(monkeypatch)
        monkeypatch.setattr(wf, "_create_resume_snapshot_output", AsyncMock(return_value=self._snapshot()))

        async def fail_after_creating() -> GetSandboxForRepositoryOutput:
            wf._sandbox_id_for_cleanup = "sb-half-built"
            wf._resume_snapshot_invalidated = snapshot_invalidated
            raise RuntimeError("agent server never came up")

        monkeypatch.setattr(wf, "_get_sandbox_for_repository", fail_after_creating)
        monkeypatch.setattr(wf, "_cancel_relay", AsyncMock())
        monkeypatch.setattr(wf, "_cleanup_sandbox", AsyncMock())
        monkeypatch.setattr(wf, "_spawn_event_relay", Mock(return_value=None))
        monkeypatch.setattr(wf, "_spawn_credential_refresh", Mock(return_value=None))
        monkeypatch.setattr(wf, "_restore_sandbox_connection_state", AsyncMock(return_value=True))

        rotation = await wf._rotate_sandbox_before_deadline("sb-old", None, None)

        assert rotation.sandbox_id is None
        assert rotation.snapshot_saved is expected_saved

    async def test_an_abandoned_rotation_puts_the_live_sandbox_back_on_the_clock_it_had(self, monkeypatch):
        wf = self._workflow(monkeypatch)
        old_deadline = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
        wf._sandbox_ttl_expires_at = old_deadline
        wf._sandbox_ttl_snapshot_taken = True
        monkeypatch.setattr(wf, "_create_resume_snapshot_output", AsyncMock(return_value=self._snapshot()))

        async def provision_replacement_then_fail() -> GetSandboxForRepositoryOutput:
            wf._sandbox_id_for_cleanup = "sb-new"
            wf._sandbox_jwt_kid = "kid-new"
            wf._sandbox_ttl_expires_at = datetime(2026, 7, 16, 18, 0, tzinfo=UTC)
            wf._sandbox_ttl_snapshot_taken = False
            raise RuntimeError("agent server never came up")

        monkeypatch.setattr(wf, "_get_sandbox_for_repository", provision_replacement_then_fail)
        monkeypatch.setattr(wf, "_cancel_relay", AsyncMock())
        monkeypatch.setattr(wf, "_cleanup_sandbox", AsyncMock())
        monkeypatch.setattr(wf, "_spawn_event_relay", Mock(return_value=None))
        monkeypatch.setattr(wf, "_spawn_credential_refresh", Mock(return_value=None))
        restore = AsyncMock(return_value=True)
        monkeypatch.setattr(wf, "_restore_sandbox_connection_state", restore)

        await wf._rotate_sandbox_before_deadline("sb-old", None, None)

        assert wf._sandbox_jwt_kid == "kid-old"
        assert wf._sandbox_ttl_expires_at == old_deadline
        assert wf._sandbox_ttl_snapshot_taken is True
        restore.assert_awaited_once_with("sb-old", "https://old.example", "old-token", "kid-old")

    async def test_a_snapshot_that_did_not_happen_leaves_the_run_where_it_is(self, monkeypatch):
        wf = self._workflow(monkeypatch)
        monkeypatch.setattr(wf, "_create_resume_snapshot_output", AsyncMock(return_value=self._snapshot(None)))
        provision = AsyncMock()
        monkeypatch.setattr(wf, "_get_sandbox_for_repository", provision)
        monkeypatch.setattr(wf, "_cancel_relay", AsyncMock())

        relay_old = self._relay("relay-old")
        refresh_old = self._relay("refresh-old")
        rotation = await wf._rotate_sandbox_before_deadline("sb-old", relay_old, refresh_old)

        assert rotation.sandbox_id is None
        assert rotation.relay_task is relay_old
        assert rotation.credential_refresh_task is refresh_old
        provision.assert_not_awaited()

    async def test_a_failed_replacement_restores_the_old_sandbox_and_its_relay(self, monkeypatch):
        wf = self._workflow(monkeypatch)
        monkeypatch.setattr(wf, "_create_resume_snapshot_output", AsyncMock(return_value=self._snapshot()))

        async def fail_after_creating() -> GetSandboxForRepositoryOutput:
            wf._sandbox_id_for_cleanup = "sb-half-built"
            raise RuntimeError("agent server never came up")

        monkeypatch.setattr(wf, "_get_sandbox_for_repository", fail_after_creating)
        monkeypatch.setattr(wf, "_cancel_relay", AsyncMock())
        cleanup = AsyncMock()
        monkeypatch.setattr(wf, "_cleanup_sandbox", cleanup)
        relay_restarted = self._relay("relay-restarted")
        monkeypatch.setattr(wf, "_spawn_event_relay", Mock(return_value=relay_restarted))
        monkeypatch.setattr(wf, "_spawn_credential_refresh", Mock(return_value=self._relay("refresh-restarted")))
        restore = AsyncMock(return_value=True)
        monkeypatch.setattr(wf, "_restore_sandbox_connection_state", restore)

        rotation = await wf._rotate_sandbox_before_deadline(
            "sb-old", self._relay("relay-old"), self._relay("refresh-old")
        )

        assert rotation.sandbox_id is None
        assert rotation.relay_task is relay_restarted
        assert rotation.routing_restored is True
        assert wf._sandbox_id_for_cleanup == "sb-old"
        assert (wf._sandbox_url, wf._sandbox_connect_token) == ("https://old.example", "old-token")
        cleanup.assert_awaited_once_with("sb-half-built", complete_stream=False)
        restore.assert_awaited_once_with("sb-old", "https://old.example", "old-token", "kid-old")


class TestProcessTaskFollowupDispatch:
    async def test_declined_steers_requeue_in_arrival_order(self, monkeypatch):
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(github_integration_id=123)
        release_initial = asyncio.Event()
        deliveries: list[tuple[str | None, bool]] = []

        async def fake_send_followup(
            *, message, artifact_ids, actor_user_id=None, message_id=None, context=None, steer=False
        ):
            deliveries.append((message, steer))
            if message == "keep working":
                await release_initial.wait()
            elif steer:
                return STEER_DECLINED_OUTCOME
            return None

        monkeypatch.setattr(workflow, "_send_followup_to_sandbox", fake_send_followup)
        monkeypatch.setattr(process_task_workflow_module.workflow, "now", Mock(return_value=Mock()))
        monkeypatch.setattr(process_task_workflow_module.workflow, "patched", Mock(return_value=True))
        monkeypatch.setattr(process_task_workflow_module.workflow, "deprecate_patch", Mock())
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())

        await workflow.send_followup_message("keep working")
        assert await workflow._dispatch_next_followup() is True
        await asyncio.sleep(0)

        await workflow.send_steer_message("use green instead")
        assert await workflow._dispatch_next_followup() is True
        await workflow.send_steer_message("use blue instead")
        assert await workflow._dispatch_next_followup() is True

        assert deliveries == [
            ("keep working", False),
            ("use green instead", True),
            ("use blue instead", True),
        ]
        assert [(followup.message, followup.steer) for followup in workflow._pending_followups] == [
            ("use green instead", False),
            ("use blue instead", False),
        ]
        release_initial.set()
        await workflow._finish_active_followup()
        assert deliveries == [
            ("keep working", False),
            ("use green instead", True),
            ("use blue instead", True),
            ("use green instead", False),
            ("use blue instead", False),
        ]

    async def test_sender_message_id_survives_concurrent_dispatch(self, monkeypatch):
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(github_integration_id=123)
        deliveries: list[tuple[str | None, str | None, bool]] = []

        async def fake_send_followup(
            *, message, artifact_ids, actor_user_id=None, message_id=None, context=None, steer=False
        ):
            deliveries.append((message, message_id, steer))
            return None

        monkeypatch.setattr(workflow, "_send_followup_to_sandbox", fake_send_followup)
        monkeypatch.setattr(process_task_workflow_module.workflow, "now", Mock(return_value=Mock()))
        monkeypatch.setattr(process_task_workflow_module.workflow, "deprecate_patch", Mock())
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())

        await workflow.send_followup_message("from Slack", [], "message-123")
        assert await workflow._dispatch_next_followup() is True
        await workflow._finish_active_followup()

        assert deliveries == [("from Slack", "message-123", False)]

    async def test_duplicate_sender_message_id_is_queued_once(self, monkeypatch):
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(github_integration_id=123)
        monkeypatch.setattr(process_task_workflow_module.workflow, "deprecate_patch", Mock())
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())

        await workflow.send_followup_message("first", [], "message-123")
        await workflow.send_followup_message("duplicate", [], "message-123")

        assert [(item.message, item.message_id) for item in workflow._pending_followups] == [("first", "message-123")]

    async def test_sender_message_id_deduplication_is_bounded(self, monkeypatch):
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(github_integration_id=123)
        monkeypatch.setattr(process_task_workflow_module.workflow, "deprecate_patch", Mock())
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())

        for index in range(501):
            await workflow.send_followup_message(f"message {index}", [], f"message-{index}")
        await workflow.send_followup_message("duplicate", [], "message-1")

        assert len(workflow._accepted_message_ids) == 500
        assert len(workflow._pending_followups) == 501

    async def test_same_message_id_from_different_senders_is_not_deduplicated(self, monkeypatch):
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(github_integration_id=123)
        monkeypatch.setattr(process_task_workflow_module.workflow, "deprecate_patch", Mock())
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())

        await workflow.send_followup_message("first", [], "message-1", actor_user_id=1)
        await workflow.send_followup_message("second", [], "message-1", actor_user_id=2)

        assert [item.message for item in workflow._pending_followups] == ["first", "second"]

    async def test_native_steer_preserves_sender_identity(self, monkeypatch):
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(github_integration_id=123)
        deliveries: list[tuple[int | None, str | None, dict[str, object] | None, bool]] = []

        async def fake_send_followup(
            *, message, artifact_ids, actor_user_id=None, message_id=None, context=None, steer=False
        ):
            deliveries.append((actor_user_id, message_id, context, steer))
            return None

        monkeypatch.setattr(workflow, "_send_followup_to_sandbox", fake_send_followup)
        monkeypatch.setattr(process_task_workflow_module.workflow, "now", Mock(return_value=Mock()))
        monkeypatch.setattr(process_task_workflow_module.workflow, "deprecate_patch", Mock())
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())

        await workflow.send_steer_message(
            "from Slack",
            [],
            "message-123",
            42,
            {"actor_slack_user_id": "U1"},
        )
        assert await workflow._dispatch_next_followup() is True
        await workflow._finish_active_followup()

        assert deliveries == [(42, "message-123", {"actor_slack_user_id": "U1"}, True)]

    async def test_terminal_drain_closes_followup_admission(self, monkeypatch):
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(github_integration_id=123)
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())

        await workflow._finish_active_followup()
        await workflow.send_steer_message("too late")

        assert workflow._pending_followup is None
        assert workflow._pending_followups == []

    async def test_final_drain_rejects_followup_while_active_dispatch_finishes(self, monkeypatch):
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(github_integration_id=123)
        release_initial = asyncio.Event()
        deliveries: list[str | None] = []

        async def fake_send_followup(
            *, message, artifact_ids, actor_user_id=None, message_id=None, context=None, steer=False
        ):
            deliveries.append(message)
            if message == "keep working":
                await release_initial.wait()
            return None

        monkeypatch.setattr(workflow, "_send_followup_to_sandbox", fake_send_followup)
        monkeypatch.setattr(process_task_workflow_module.workflow, "now", Mock(return_value=Mock()))
        monkeypatch.setattr(process_task_workflow_module.workflow, "patched", Mock(return_value=True))
        monkeypatch.setattr(process_task_workflow_module.workflow, "deprecate_patch", Mock())
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())

        await workflow.send_followup_message("keep working")
        assert await workflow._dispatch_next_followup() is True
        await asyncio.sleep(0)

        finish_task = asyncio.create_task(workflow._finish_active_followup())
        await asyncio.sleep(0)
        assert workflow._shutting_down is True

        await workflow.send_followup_message("arrived during drain")
        release_initial.set()
        await finish_task

        assert deliveries == ["keep working"]
        assert workflow._pending_followups == []

    async def test_cancellation_stops_active_followup_and_discards_queue(self, monkeypatch):
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(github_integration_id=123)
        followup_cancelled = asyncio.Event()

        async def fake_send_followup(
            *, message, artifact_ids, actor_user_id=None, message_id=None, context=None, steer=False
        ):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                followup_cancelled.set()
                raise

        monkeypatch.setattr(workflow, "_send_followup_to_sandbox", fake_send_followup)
        monkeypatch.setattr(process_task_workflow_module.workflow, "now", Mock(return_value=Mock()))
        monkeypatch.setattr(process_task_workflow_module.workflow, "deprecate_patch", Mock())
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())

        await workflow.send_followup_message("keep working")
        assert await workflow._dispatch_next_followup() is True
        await asyncio.sleep(0)
        await workflow.send_followup_message("queued work")

        await workflow.complete_task("cancelled", "Stopped by user")
        await workflow._finish_active_followup()

        assert followup_cancelled.is_set()
        assert workflow._active_followup_task is None
        assert workflow._pending_followup is None
        assert workflow._pending_followups == []

    async def test_completion_waits_for_declined_steer_fallback(self, monkeypatch):
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(github_integration_id=123)
        release_steer = asyncio.Event()
        deliveries: list[tuple[str | None, bool]] = []

        async def fake_send_followup(
            *, message, artifact_ids, actor_user_id=None, message_id=None, context=None, steer=False
        ):
            deliveries.append((message, steer))
            if steer:
                await release_steer.wait()
                return STEER_DECLINED_OUTCOME
            return None

        monkeypatch.setattr(workflow, "_send_followup_to_sandbox", fake_send_followup)
        monkeypatch.setattr(process_task_workflow_module.workflow, "now", Mock(return_value=Mock()))
        monkeypatch.setattr(process_task_workflow_module.workflow, "patched", Mock(return_value=True))
        monkeypatch.setattr(process_task_workflow_module.workflow, "deprecate_patch", Mock())
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())

        await workflow.send_steer_message("finish in green")
        assert await workflow._dispatch_next_followup() is True
        await asyncio.sleep(0)

        await workflow.complete_task()
        release_steer.set()
        await workflow._finish_active_followup()

        assert deliveries == [("finish in green", True), ("finish in green", False)]
        assert workflow._pending_followup is None
        assert workflow._pending_followups == []


class TestFollowupDeliveryFailureBookkeeping:
    def _workflow(self, monkeypatch, *, mode: str, patched: bool):
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(github_integration_id=123, state={"mode": mode})
        emitted: list[EmitProgressInput] = []

        async def fake_execute_activity(_activity, activity_input, **_kwargs):
            if isinstance(activity_input, SendFollowupToSandboxInput):
                raise RuntimeError("delivery failed")
            if isinstance(activity_input, EmitProgressInput):
                emitted.append(activity_input)
            return None

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", fake_execute_activity)
        monkeypatch.setattr(process_task_workflow_module.workflow, "patched", Mock(return_value=patched))
        monkeypatch.setattr(process_task_workflow_module.workflow, "deprecate_patch", Mock())
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())
        return workflow, emitted

    async def test_failed_interactive_delivery_releases_the_message_for_retry(self, monkeypatch):
        workflow, emitted = self._workflow(monkeypatch, mode="interactive", patched=True)

        await workflow.send_followup_message("try this", [], "msg-1")
        assert len(workflow._pending_followups) == 1

        result = await workflow._send_followup_to_sandbox("try this", [], message_id="msg-1")

        assert result is None
        assert workflow._task_completed is False
        assert workflow._completion_status == "completed"
        assert [(e.step, e.status) for e in emitted] == [("followup_delivery", "failed")]

        await workflow.send_followup_message("try this", [], "msg-1")
        assert len(workflow._pending_followups) == 2

    @pytest.mark.parametrize("mode,patched", [("interactive", False), ("background", True)])
    async def test_failed_delivery_terminalizes_when_keep_alive_does_not_apply(self, monkeypatch, mode, patched):
        workflow, emitted = self._workflow(monkeypatch, mode=mode, patched=patched)

        result = await workflow._send_followup_to_sandbox("try this", [], message_id="msg-1")

        assert result is None
        assert workflow._task_completed is True
        assert workflow._completion_status == "failed"
        assert workflow._completion_error_type == "followup_delivery_failed"
        assert emitted == []


@pytest.mark.django_db
class TestProcessTaskWorkflowUnit:
    def test_quota_recheck_not_scheduled_for_non_pr_runs(self):
        # Research / repo-selection sessions run as SIGNAL_REPORT-origin tasks with
        # create_pr=False; scheduling the recheck for them would let the quota gate cancel
        # in-flight research.
        wf = ProcessTaskWorkflow()
        wf._context = dataclasses.replace(
            _build_context(github_integration_id=None), origin_product="signal_report", create_pr=False
        )
        assert wf._self_driving_quota_recheck_scheduled() is False

    async def test_final_sandbox_cleanup_completes_the_run_stream(self, monkeypatch):
        cleanup_inputs: list[CleanupSandboxInput] = []

        async def fake_execute_activity(activity_fn, activity_input, **kwargs):
            assert activity_fn is cleanup_sandbox
            cleanup_inputs.append(activity_input)

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", fake_execute_activity)
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(github_integration_id=123)

        await workflow._cleanup_sandbox("sandbox-123", complete_stream=True)

        assert cleanup_inputs == [
            CleanupSandboxInput(
                sandbox_id="sandbox-123",
                run_id="run-id",
                complete_stream_on_cleanup=True,
            )
        ]

    async def test_final_sandbox_cleanup_completes_stream_after_cleanup_retries_fail(self, monkeypatch):
        activity_calls: list[object] = []

        async def fake_execute_activity(activity_fn, activity_input, **kwargs):
            activity_calls.append(activity_fn)
            if activity_fn is cleanup_sandbox:
                raise RuntimeError("destroy failed")
            assert activity_fn is complete_run_stream
            assert activity_input == CompleteRunStreamInput(run_id="run-id")

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", fake_execute_activity)
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(github_integration_id=123)

        with pytest.raises(RuntimeError, match="destroy failed"):
            await workflow._cleanup_sandbox("sandbox-123", complete_stream=True)

        assert activity_calls == [cleanup_sandbox, complete_run_stream]

    async def test_finalizes_run_stream_without_a_sandbox(self, monkeypatch):
        stream_inputs: list[CompleteRunStreamInput] = []

        async def fake_execute_activity(activity_fn, activity_input, **kwargs):
            assert activity_fn is complete_run_stream
            stream_inputs.append(activity_input)

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", fake_execute_activity)
        workflow = ProcessTaskWorkflow()

        await workflow._complete_run_stream("run-id")

        assert stream_inputs == [CompleteRunStreamInput(run_id="run-id")]

    async def test_send_followup_message_can_arrive_before_context_is_loaded(self, monkeypatch):
        logger = Mock()
        deprecate_patch = Mock()
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", logger)
        monkeypatch.setattr(process_task_workflow_module.workflow, "deprecate_patch", deprecate_patch)
        workflow = ProcessTaskWorkflow()

        await workflow.send_followup_message("first", ["artifact-1"])
        await workflow.send_steer_message("second", ["artifact-2"])
        await workflow.send_followup_message("legacy-steer", ["artifact-3"], True)

        assert workflow._pending_followups == [
            PendingFollowup(message="first", artifact_ids=["artifact-1"]),
            PendingFollowup(message="second", artifact_ids=["artifact-2"], steer=True, sequence=1),
            PendingFollowup(message="legacy-steer", artifact_ids=["artifact-3"], steer=True, sequence=2),
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
        assert logger.info.call_count == 3

    async def test_send_permission_response_can_arrive_before_context_is_loaded(self, monkeypatch):
        logger = Mock()
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", logger)
        workflow = ProcessTaskWorkflow()

        await workflow.send_permission_response(
            {
                "request_id": "perm-1",
                "option_id": "allow",
                "actor_user_id": 42,
                "actor_slack_user_id": "U123",
                "broker_reason": "destructive_policy_auto_allow",
            }
        )

        assert workflow._pending_permission_responses == [
            PendingPermissionResponse(
                request_id="perm-1",
                option_id="allow",
                actor_user_id=42,
                actor_slack_user_id="U123",
                broker_reason="destructive_policy_auto_allow",
            )
        ]
        logger.info.assert_called_once_with(
            "permission_response_signal_received",
            extra={
                "run_id": None,
                "request_id": "perm-1",
                "option_id": "allow",
                "actor_user_id": 42,
                "is_denial": False,
            },
        )

    async def test_denial_schedules_guidance_before_permission_response(self, monkeypatch):
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(github_integration_id=123)
        activity_calls: list[tuple[object, object]] = []

        async def fake_execute_activity(activity_fn, activity_input, **_kwargs):
            activity_calls.append((activity_fn, activity_input))
            return None

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", fake_execute_activity)

        await workflow._send_permission_response_to_sandbox(
            PendingPermissionResponse(
                request_id="perm-1",
                option_id="reject",
                actor_user_id=42,
                actor_slack_user_id="U123",
                is_denial=True,
                denial_message="Please choose another path.",
                broker_reason="slack_human_response",
            )
        )

        assert [call[0] for call in activity_calls] == [
            send_permission_denial_guidance,
            send_permission_response_to_sandbox,
        ]
        assert activity_calls[0][1] == SendPermissionDenialGuidanceInput(
            run_id="run-id",
            request_id="perm-1",
            actor_user_id=42,
            denial_message="Please choose another path.",
        )
        assert activity_calls[1][1] == SendPermissionResponseToSandboxInput(
            run_id="run-id",
            request_id="perm-1",
            option_id="reject",
            actor_user_id=42,
            actor_slack_user_id="U123",
            is_denial=True,
            broker_reason="slack_human_response",
        )

    async def test_denial_guidance_failure_still_delivers_permission_response(self, monkeypatch):
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(github_integration_id=123)
        activity_calls: list[object] = []

        async def fake_execute_activity(activity_fn, activity_input, **_kwargs):
            activity_calls.append(activity_fn)
            if activity_fn is send_permission_denial_guidance:
                raise RuntimeError("sandbox unavailable")
            return None

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", fake_execute_activity)

        await workflow._send_permission_response_to_sandbox(
            PendingPermissionResponse(
                request_id="perm-1",
                option_id="reject",
                actor_user_id=42,
                is_denial=True,
                denial_message="Please choose another path.",
            )
        )

        assert activity_calls == [send_permission_denial_guidance, send_permission_response_to_sandbox]

    async def test_approval_skips_denial_guidance_activity(self, monkeypatch):
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(github_integration_id=123)
        activity_calls: list[object] = []

        async def fake_execute_activity(activity_fn, _activity_input, **_kwargs):
            activity_calls.append(activity_fn)
            return None

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", fake_execute_activity)

        await workflow._send_permission_response_to_sandbox(
            PendingPermissionResponse(
                request_id="perm-1",
                option_id="allow",
                actor_user_id=42,
                broker_reason="slack_human_response",
            )
        )

        assert activity_calls == [send_permission_response_to_sandbox]

    async def test_delivery_failure_does_not_raise_and_posts_thread_notice(self, monkeypatch):
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(github_integration_id=123)
        workflow._slack_thread_context = {"channel": "C1", "thread_ts": "1.0"}
        activity_calls: list[object] = []

        async def fake_execute_activity(activity_fn, _activity_input, **_kwargs):
            activity_calls.append(activity_fn)
            if activity_fn is send_permission_response_to_sandbox:
                raise RuntimeError("sandbox unavailable")
            return None

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", fake_execute_activity)

        await workflow._send_permission_response_to_sandbox(
            PendingPermissionResponse(request_id="perm-1", option_id="allow", actor_user_id=42)
        )

        assert activity_calls == [send_permission_response_to_sandbox, post_permission_delivery_failure_notice]

    async def test_pending_responses_are_drained_before_drainer_exits_on_completion(self, monkeypatch):
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())
        monkeypatch.setattr(process_task_workflow_module.workflow, "now", Mock(return_value=None))

        async def fake_wait_condition(condition):
            assert condition()

        monkeypatch.setattr(process_task_workflow_module.workflow, "wait_condition", fake_wait_condition)

        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(github_integration_id=123)
        workflow._task_completed = True
        workflow._pending_permission_responses = [
            PendingPermissionResponse(request_id="perm-1", option_id="allow", actor_user_id=42),
            PendingPermissionResponse(request_id="perm-2", option_id="reject", actor_user_id=42),
        ]
        delivered: list[str] = []

        async def fake_execute_activity(activity_fn, activity_input, **_kwargs):
            if activity_fn is send_permission_response_to_sandbox:
                delivered.append(activity_input.request_id)
            return None

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", fake_execute_activity)

        await workflow._deliver_pending_permission_responses()

        assert delivered == ["perm-1", "perm-2"]
        assert workflow._pending_permission_responses == []

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

    def test_parse_inputs_rebuilds_babysit_journal_from_resumed_sandbox(self):
        payload = {
            "run_id": "r1",
            "resumed_sandbox": {
                "sandbox_id": "s1",
                "sandbox_url": "https://sandbox",
                "connect_token": None,
                "ci_repetitions": 0,
                "pr_fingerprint": None,
                "pr_progress_emitted": False,
                "first_user_message_received": False,
                "is_agent_design_enabled": False,
                "last_active_time": None,
                "babysit_journal": {
                    "threads": {"T1": "C1"},
                    "comment_ids": ["M1"],
                    "head_sha": "abc",
                    "head_keys": ["CI/backend"],
                },
            },
        }

        parsed = ProcessTaskWorkflow.parse_inputs([json.dumps(payload)])

        # Must come back as a BabysitJournal, not a raw dict, so the next babysit poll can
        # call .attention() on it instead of raising AttributeError.
        assert parsed.resumed_sandbox is not None
        journal = parsed.resumed_sandbox.babysit_journal
        assert isinstance(journal, BabysitJournal)
        assert journal.threads == {"T1": "C1"}

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

    async def test_credential_refresh_credentials_unavailable_does_not_mark_sandbox_gone(self, monkeypatch):
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(github_integration_id=123)
        logger = Mock()
        refresh_loop_mock = AsyncMock(return_value=CredentialRefreshExitReason.CREDENTIALS_UNAVAILABLE)

        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", logger)
        monkeypatch.setattr(process_task_workflow_module, "run_credential_refresh_loop", refresh_loop_mock)

        await workflow._run_credential_refresh_until_sandbox_gone("sandbox-123")

        assert workflow._sandbox_gone is False
        logger.warning.assert_called_once_with(
            "credential_refresh_stopped_credentials_unavailable",
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
        cleanup_sandbox_mock.assert_awaited_once_with("sandbox-123", complete_stream=True)

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
        complete_run_stream_mock = AsyncMock()

        monkeypatch.setattr(workflow, "_get_task_processing_context", get_task_processing_context_mock)
        monkeypatch.setattr(workflow, "_update_task_run_status", update_task_run_status_mock)
        monkeypatch.setattr(workflow, "_track_workflow_event", track_workflow_event_mock)
        monkeypatch.setattr(workflow, "_post_slack_update", post_slack_update_mock)
        monkeypatch.setattr(workflow, "_complete_run_stream", complete_run_stream_mock)

        result = await workflow.run(ProcessTaskInput(run_id="run-id"))

        assert result.success is False
        assert result.error == "database connection closed"
        assert result.sandbox_id is None
        update_task_run_status_mock.assert_awaited_once_with(
            "failed",
            error_message="database connection closed",
            run_id="run-id",
            error_type="RuntimeError",
        )
        track_workflow_event_mock.assert_not_awaited()
        post_slack_update_mock.assert_not_awaited()
        complete_run_stream_mock.assert_awaited_once_with("run-id")

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
            error_type="SandboxNotRunningError",
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

    @pytest.mark.parametrize(
        "origin_product, pr_progress_emitted, ci_repetitions, expected_status",
        [
            (None, False, 1, "completed"),
            ("user_created", False, 1, "completed"),
            # Onboarding runs are one-shot, so a vanished sandbox is a failed setup rather than a
            # resumable snapshot.
            ("onboarding", False, 1, "failed"),
            # Unless the PR is already open: the wizard reads the terminal status, so a downgrade
            # would report a failed install over a PR the user can merge.
            ("onboarding", True, 1, "completed"),
            # No follow-up round ever ran, so the empty PR latch is unobserved rather than evidence
            # of no PR. Downgrading here would fail a run whose PR the loop never got to look at.
            ("onboarding", False, 0, "completed"),
        ],
    )
    async def test_run_completes_when_credential_refresh_detects_sandbox_gone(
        self, monkeypatch, origin_product, pr_progress_emitted, ci_repetitions, expected_status
    ):
        workflow = ProcessTaskWorkflow()
        workflow._pr_progress_emitted = pr_progress_emitted
        workflow._ci_repetitions = ci_repetitions
        context = _build_context(github_integration_id=123, origin_product=origin_product)
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

        # run() awaits the permission-response drainer on the completion path; outside a
        # Temporal event loop the real workflow.wait_condition raises immediately.
        async def fake_wait_condition(condition):
            while not condition():
                await asyncio.sleep(0)

        monkeypatch.setattr(process_task_workflow_module.workflow, "wait_condition", fake_wait_condition)

        result = await workflow.run(ProcessTaskInput(run_id="run-id"))

        assert result.success is True
        assert workflow._completion_status == expected_status
        update_task_run_status_mock.assert_any_await(
            expected_status,
            error_message=SANDBOX_GONE_ERROR_MESSAGE,
            error_type=None,
            timeout_marker=SANDBOX_GONE_STATE_KEY,
        )
        cleanup_sandbox_mock.assert_awaited_once_with("sandbox-123", complete_stream=True)

    @pytest.mark.parametrize(
        "event, origin_product, pr_progress_emitted, ci_repetitions, expected_status, expected_kwargs",
        [
            (
                process_task_workflow_module.TaskEvent.TIMEOUT_REACHED,
                None,
                False,
                1,
                "completed",
                {"timed_out_inactivity": True},
            ),
            (
                process_task_workflow_module.TaskEvent.TIMEOUT_REACHED,
                "onboarding",
                False,
                1,
                "failed",
                {"timed_out_inactivity": True},
            ),
            # An onboarding run that already opened its PR delivered its install; the CI
            # follow-up loop simply ran out, so the wizard must still read success.
            (
                process_task_workflow_module.TaskEvent.TIMEOUT_REACHED,
                "onboarding",
                True,
                1,
                "completed",
                {"timed_out_inactivity": True},
            ),
            # The follow-up loop never ran, so nothing ever checked for a PR. Without that
            # observation the empty latch proves nothing and the run keeps completing.
            (
                process_task_workflow_module.TaskEvent.TIMEOUT_REACHED,
                "onboarding",
                False,
                0,
                "completed",
                {"timed_out_inactivity": True},
            ),
            (
                process_task_workflow_module.TaskEvent.MAX_DURATION_REACHED,
                None,
                False,
                1,
                "failed",
                {"timeout_marker": TIMED_OUT_WALL_CLOCK_STATE_KEY},
            ),
            (
                process_task_workflow_module.TaskEvent.MAX_DURATION_REACHED,
                "onboarding",
                False,
                1,
                "failed",
                {"timeout_marker": TIMED_OUT_WALL_CLOCK_STATE_KEY},
            ),
        ],
    )
    async def test_run_terminalizes_timeouts_with_their_marker(
        self, monkeypatch, event, origin_product, pr_progress_emitted, ci_repetitions, expected_status, expected_kwargs
    ):
        # The wall-clock cap is a failure for every origin; the inactivity timeout only fails for
        # onboarding runs that delivered nothing, because other origins resume from the timed-out
        # run and a PR-bearing onboarding run already succeeded.
        workflow = ProcessTaskWorkflow()
        workflow._pr_progress_emitted = pr_progress_emitted
        workflow._ci_repetitions = ci_repetitions
        context = _build_context(github_integration_id=123, origin_product=origin_product)
        update_task_run_status_mock = AsyncMock()

        monkeypatch.setattr(workflow, "_get_task_processing_context", AsyncMock(return_value=context))
        monkeypatch.setattr(workflow, "_update_task_run_status", update_task_run_status_mock)
        monkeypatch.setattr(workflow, "_track_workflow_event", AsyncMock())
        monkeypatch.setattr(workflow, "_post_slack_update", AsyncMock())
        monkeypatch.setattr(workflow, "_read_sandbox_logs", AsyncMock())
        monkeypatch.setattr(workflow, "_cleanup_sandbox", AsyncMock())
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
        monkeypatch.setattr(workflow, "_wait_for_event", AsyncMock(return_value=event))
        monkeypatch.setattr(process_task_workflow_module.workflow, "patched", Mock(return_value=True))
        # workflow.logger resolves the replay flag off the workflow event loop, which this
        # loop-free unit test doesn't have.
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())

        result = await workflow.run(ProcessTaskInput(run_id="run-id"))

        assert result.success is True
        update_task_run_status_mock.assert_any_await(expected_status, **expected_kwargs)

    @pytest.mark.parametrize(
        "create_pr, pr_progress_emitted, ci_repetitions, expected",
        [
            # The follow-up loop looked and found no PR, so the run provably delivered nothing.
            (True, False, 1, True),
            # The loop looked and found one: the install landed.
            (True, True, 1, False),
            # The loop never ran (disabled for the org, or the exit landed inside the first
            # follow-up delay), so the empty latch is an absence of observation, not of a PR.
            (True, False, 0, False),
            # No PR was ever expected, so there is nothing to observe and nothing was delivered.
            (False, False, 0, True),
        ],
    )
    def test_onboarding_exit_is_failure_requires_an_observed_pr_absence(
        self, monkeypatch, create_pr, pr_progress_emitted, ci_repetitions, expected
    ):
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(github_integration_id=123, origin_product="onboarding", create_pr=create_pr)
        workflow._pr_progress_emitted = pr_progress_emitted
        workflow._ci_repetitions = ci_repetitions
        monkeypatch.setattr(process_task_workflow_module.workflow, "patched", Mock(return_value=True))

        assert workflow._onboarding_exit_is_failure() is expected

    async def test_run_keeps_completing_inactivity_timeouts_before_the_lifecycle_patch(self, monkeypatch):
        # Replaying a pre-patch history: the onboarding FAILED terminalization must not apply, or the
        # replay would write a different terminal status than the recorded one.
        workflow = ProcessTaskWorkflow()
        context = _build_context(github_integration_id=123, origin_product="onboarding")
        update_task_run_status_mock = AsyncMock()

        monkeypatch.setattr(workflow, "_get_task_processing_context", AsyncMock(return_value=context))
        monkeypatch.setattr(workflow, "_update_task_run_status", update_task_run_status_mock)
        monkeypatch.setattr(workflow, "_track_workflow_event", AsyncMock())
        monkeypatch.setattr(workflow, "_post_slack_update", AsyncMock())
        monkeypatch.setattr(workflow, "_read_sandbox_logs", AsyncMock())
        monkeypatch.setattr(workflow, "_cleanup_sandbox", AsyncMock())
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
        monkeypatch.setattr(
            workflow, "_wait_for_event", AsyncMock(return_value=process_task_workflow_module.TaskEvent.TIMEOUT_REACHED)
        )
        # The patch helpers short-circuit to "enabled" outside a workflow, so the replay case only
        # exists once in_workflow() is true and the marker is absent.
        monkeypatch.setattr(process_task_workflow_module.workflow, "in_workflow", Mock(return_value=True))
        monkeypatch.setattr(process_task_workflow_module.workflow, "patched", Mock(return_value=False))

        result = await workflow.run(ProcessTaskInput(run_id="run-id"))

        assert result.success is True
        update_task_run_status_mock.assert_any_await("completed", timed_out_inactivity=True)

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
            sandbox_creation_timeout_seconds=30 * 60,
        )
        created = CreateSandboxForRepositoryOutput(
            sandbox_id="sandbox-123",
            sandbox_url="https://sandbox.example",
            connect_token="connect-token",
        )
        activity_calls: list[object] = []
        create_activity_kwargs: dict[str, Any] = {}

        async def fake_execute_activity(activity_fn, *args, **kwargs):
            activity_calls.append(activity_fn)
            if activity_fn is prepare_sandbox_for_repository:
                return prepared
            if activity_fn is create_sandbox_for_repository:
                create_activity_kwargs.update(kwargs)
                return created
            if activity_fn is emit_progress_activity:
                return None
            raise AssertionError(f"Unexpected activity call: {activity_fn}")

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", fake_execute_activity)

        result = await workflow._get_sandbox_for_repository()

        assert result.sandbox_id == "sandbox-123"
        assert workflow._sandbox_id_for_cleanup == "sandbox-123"
        assert create_activity_kwargs["start_to_close_timeout"] == timedelta(minutes=30)
        assert clone_repository_in_sandbox not in activity_calls
        assert checkout_branch_in_sandbox not in activity_calls

    async def test_sandbox_creation_stops_when_task_completes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        process_workflow = ProcessTaskWorkflow()
        process_workflow._context = _build_context(github_integration_id=None)
        prepared = PrepareSandboxForRepositoryOutput(
            sandbox_name="sandbox-name",
            repository=None,
            github_token="",
            branch=None,
            environment_variables={},
            snapshot_id=None,
            snapshot_external_id=None,
            used_snapshot=False,
            should_create_snapshot=True,
            shallow_clone=True,
            image_source="docker_base_image",
            image_source_label="local Docker sandbox image",
            sandbox_creation_timeout_seconds=30 * 60,
            sandbox_creation_cancellable=True,
        )
        creation_cancelled = asyncio.Event()
        start_activity_kwargs: dict[str, Any] = {}

        async def blocked_creation() -> CreateSandboxForRepositoryOutput:
            try:
                await asyncio.Event().wait()
                raise AssertionError("sandbox creation unexpectedly completed")
            finally:
                creation_cancelled.set()

        def fake_start_activity(*args: Any, **kwargs: Any) -> asyncio.Task[CreateSandboxForRepositoryOutput]:
            start_activity_kwargs.update(kwargs)
            return asyncio.create_task(blocked_creation())

        async def fake_wait_condition(predicate: Callable[[], bool]) -> None:
            process_workflow._task_completed = True
            assert predicate()

        monkeypatch.setattr(process_task_workflow_module.workflow, "patched", lambda _patch_id: True)
        monkeypatch.setattr(process_task_workflow_module.workflow, "start_activity", fake_start_activity)
        monkeypatch.setattr(process_task_workflow_module.workflow, "wait_condition", fake_wait_condition)

        with pytest.raises(process_task_workflow_module._TaskCompletedDuringSandboxCreation):
            await process_workflow._run_sandbox_creation_activity(prepared)

        assert creation_cancelled.is_set()
        assert start_activity_kwargs["start_to_close_timeout"] == timedelta(minutes=30)
        assert start_activity_kwargs["heartbeat_timeout"] == timedelta(seconds=30)
        assert (
            start_activity_kwargs["cancellation_type"]
            == process_task_workflow_module.workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED
        )

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

        async def fake_execute_activity(activity_fn: Any, *args: Any, **kwargs: Any) -> Any:
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

    async def test_get_sandbox_for_repository_clones_every_repository(self, monkeypatch):
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(
            github_integration_id=123,
            state={"repositories": ["posthog/posthog", "posthog/code"]},
            custom_image_name="posthog-dev-stack",
        )
        prepared = PrepareSandboxForRepositoryOutput(
            sandbox_name="sandbox-name",
            repository="posthog/posthog",
            github_token="ghs_token",
            branch=None,
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
        cloned: list[str] = []
        clone_options: dict[str, dict[str, Any]] = {}

        async def fake_execute_activity(activity_fn: Any, *args: Any, **kwargs: Any) -> Any:
            if activity_fn is prepare_sandbox_for_repository:
                return prepared
            if activity_fn is create_sandbox_for_repository:
                return created
            if activity_fn is clone_repository_in_sandbox:
                cloned.append(args[0].repository)
                clone_options[args[0].repository] = kwargs
                return None
            if activity_fn is emit_progress_activity:
                return None
            raise AssertionError(f"Unexpected activity call: {activity_fn}")

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", fake_execute_activity)
        monkeypatch.setattr(process_task_workflow_module.workflow, "patched", lambda _: True)

        result = await workflow._get_sandbox_for_repository()

        assert cloned == ["posthog/posthog", "posthog/code"]
        assert clone_options["posthog/posthog"]["start_to_close_timeout"] == timedelta(minutes=20)
        assert clone_options["posthog/posthog"]["retry_policy"].maximum_attempts == 3
        assert clone_options["posthog/code"]["start_to_close_timeout"] == timedelta(minutes=5)
        assert clone_options["posthog/code"]["retry_policy"].maximum_attempts == 3
        assert result.clone_ms is None

    async def test_get_sandbox_for_repository_uses_desktop_budget_for_snapshot_checkout(self, monkeypatch):
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(
            github_integration_id=123,
            repository="posthog/posthog",
            custom_image_name="posthog-dev-stack",
        )
        prepared = PrepareSandboxForRepositoryOutput(
            sandbox_name="sandbox-name",
            repository="posthog/posthog",
            github_token="ghs_token",
            branch="feature-branch",
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
        checkout_options: dict[str, Any] = {}

        async def fake_execute_activity(activity_fn: Any, *args: Any, **kwargs: Any) -> Any:
            if activity_fn is prepare_sandbox_for_repository:
                return prepared
            if activity_fn is create_sandbox_for_repository:
                return created
            if activity_fn is checkout_branch_in_sandbox:
                checkout_options.update(kwargs)
                return None
            if activity_fn is emit_progress_activity:
                return None
            raise AssertionError(f"Unexpected activity call: {activity_fn}")

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", fake_execute_activity)

        await workflow._get_sandbox_for_repository()

        assert checkout_options["start_to_close_timeout"] == timedelta(minutes=20)
        assert checkout_options["retry_policy"].maximum_attempts == 3

    async def test_overlap_releases_agent_after_primary_clone_and_materializes_failed_secondary(self, monkeypatch):
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(
            github_integration_id=123,
            state={"repositories": ["posthog/posthog", "posthog/code"]},
        )
        workflow._context.overlap_clone_boot_enabled = True
        prepared = PrepareSandboxForRepositoryOutput(
            sandbox_name="sandbox-name",
            repository="posthog/posthog",
            github_token="ghs_token",
            branch=None,
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
        secondary_clone_started = asyncio.Event()
        release_secondary_clone = asyncio.Event()
        ready_inputs: list[Any] = []

        async def fake_execute_activity(activity_fn: Any, *args: Any, **kwargs: Any) -> Any:
            if activity_fn is prepare_sandbox_for_repository:
                return prepared
            if activity_fn is create_sandbox_for_repository:
                return created
            if activity_fn is launch_agent_server:
                return StartAgentServerOutput(sandbox_url=created.sandbox_url)
            if activity_fn is clone_repository_in_sandbox:
                if args[0].repository == "posthog/code":
                    secondary_clone_started.set()
                    await release_secondary_clone.wait()
                    raise RuntimeError("secondary clone failed")
                else:
                    await secondary_clone_started.wait()
                return None
            if activity_fn is mark_repo_ready:
                ready_inputs.append(args[0])
                if args[0].release_barrier:
                    assert secondary_clone_started.is_set()
                    assert not release_secondary_clone.is_set()
                    release_secondary_clone.set()
                else:
                    assert release_secondary_clone.is_set()
                return None
            if activity_fn is emit_progress_activity:
                return None
            raise AssertionError(f"Unexpected activity call: {activity_fn}")

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", fake_execute_activity)
        monkeypatch.setattr(process_task_workflow_module.workflow, "patched", lambda _: True)
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())

        result = await workflow._get_sandbox_for_repository()

        assert result.agent_server_launched is True
        assert release_secondary_clone.is_set()
        assert len(ready_inputs) == 2
        assert ready_inputs[0].failed_repositories is None
        assert ready_inputs[0].release_barrier is True
        assert ready_inputs[1].failed_repositories == ["posthog/code"]
        assert ready_inputs[1].release_barrier is False

    async def test_overlap_releases_agent_and_continues_when_primary_clone_fails(self, monkeypatch):
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(
            github_integration_id=123,
            state={"repositories": ["posthog/posthog"]},
        )
        workflow._context.overlap_clone_boot_enabled = True
        prepared = PrepareSandboxForRepositoryOutput(
            sandbox_name="sandbox-name",
            repository="posthog/posthog",
            github_token="ghs_token",
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
        calls: list[object] = []
        progress: list[Any] = []
        ready_inputs: list[Any] = []

        async def fake_execute_activity(activity_fn: Any, *args: Any, **kwargs: Any) -> Any:
            calls.append(activity_fn)
            if activity_fn is prepare_sandbox_for_repository:
                return prepared
            if activity_fn is create_sandbox_for_repository:
                return created
            if activity_fn is launch_agent_server:
                return StartAgentServerOutput(sandbox_url=created.sandbox_url)
            if activity_fn is clone_repository_in_sandbox:
                raise RuntimeError("clone timed out")
            if activity_fn is mark_repo_ready:
                ready_inputs.append(args[0])
                return None
            if activity_fn is emit_progress_activity:
                progress.append(args[0])
                return None
            raise AssertionError(f"Unexpected activity call: {activity_fn}")

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", fake_execute_activity)
        monkeypatch.setattr(process_task_workflow_module.workflow, "patched", lambda _: True)
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())

        result = await workflow._get_sandbox_for_repository()

        assert result.agent_server_launched is True
        assert mark_repo_ready in calls
        assert checkout_branch_in_sandbox not in calls
        assert len(ready_inputs) == 1
        assert ready_inputs[0].failed_repositories == ["posthog/posthog"]
        assert ready_inputs[0].release_barrier is True
        assert progress[-1].label == "Repository clone failed; continuing without it"
        assert progress[-1].detail == "Could not clone: posthog/posthog"

    async def test_clone_failure_does_not_hide_dead_sandbox_failure(self, monkeypatch):
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(github_integration_id=123)
        workflow._context.overlap_clone_boot_enabled = True
        prepared = PrepareSandboxForRepositoryOutput(
            sandbox_name="sandbox-name",
            repository="posthog/posthog",
            github_token="ghs_token",
            branch=None,
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
        calls: list[object] = []

        async def fake_execute_activity(activity_fn: Any, *args: Any, **kwargs: Any) -> Any:
            calls.append(activity_fn)
            if activity_fn is prepare_sandbox_for_repository:
                return prepared
            if activity_fn is create_sandbox_for_repository:
                return created
            if activity_fn is launch_agent_server:
                return StartAgentServerOutput(sandbox_url=created.sandbox_url)
            if activity_fn is clone_repository_in_sandbox:
                raise ApplicationError("sandbox disappeared", type="SandboxNotFoundError")
            if activity_fn is emit_progress_activity:
                return None
            raise AssertionError(f"Unexpected activity call: {activity_fn}")

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", fake_execute_activity)
        monkeypatch.setattr(process_task_workflow_module.workflow, "patched", lambda _: True)

        with pytest.raises(ApplicationError, match="sandbox disappeared"):
            await workflow._get_sandbox_for_repository()

        assert mark_repo_ready not in calls

    async def test_overlap_preserves_legacy_repo_ready_order_on_replay(self, monkeypatch):
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(
            github_integration_id=123,
            state={"repositories": ["posthog/posthog", "posthog/code"]},
        )
        workflow._context.overlap_clone_boot_enabled = True
        prepared = PrepareSandboxForRepositoryOutput(
            sandbox_name="sandbox-name",
            repository="posthog/posthog",
            github_token="ghs_token",
            branch=None,
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
        calls: list[str] = []

        async def fake_execute_activity(activity_fn: Any, *args: Any, **kwargs: Any) -> Any:
            if activity_fn is prepare_sandbox_for_repository:
                return prepared
            if activity_fn is create_sandbox_for_repository:
                return created
            if activity_fn is launch_agent_server:
                return StartAgentServerOutput(sandbox_url=created.sandbox_url)
            if activity_fn is clone_repository_in_sandbox:
                calls.append(f"clone:{args[0].repository}")
                return None
            if activity_fn is mark_repo_ready:
                calls.append("ready")
                return None
            if activity_fn is emit_progress_activity:
                return None
            raise AssertionError(f"Unexpected activity call: {activity_fn}")

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", fake_execute_activity)
        monkeypatch.setattr(process_task_workflow_module.workflow, "patched", lambda _: False)

        await workflow._get_sandbox_for_repository()

        assert calls == ["clone:posthog/posthog", "clone:posthog/code", "ready"]

    @pytest.mark.parametrize(
        "custom_image_name, expected_image_source, expected_image_source_label",
        [
            (None, "base_image", "published sandbox base image"),
            ("sandbox-custom-abc", "custom_image", "custom base image sandbox-custom-abc"),
        ],
    )
    async def test_get_sandbox_for_repository_falls_back_to_fresh_sandbox_when_resume_injection_fails(
        self, monkeypatch, custom_image_name, expected_image_source, expected_image_source_label
    ):
        workflow = ProcessTaskWorkflow()
        workflow._context = _build_context(
            github_integration_id=123,
            state={"snapshot_external_id": "im-abc123", "resume_from_run_id": "previous-run-id"},
            use_modal_vm_sandbox=custom_image_name is not None,
            custom_image_name=custom_image_name,
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
        monkeypatch.setattr(process_task_workflow_module.workflow, "patched", lambda _: True)

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
        assert fresh_prepared.image_source == expected_image_source
        assert fresh_prepared.image_source_label == expected_image_source_label
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

        cleanup_sandbox_mock.assert_awaited_once_with("sandbox-123", complete_stream=True)
        if expect_resume_snapshot_call:
            create_resume_snapshot_mock.assert_awaited_once_with("sandbox-123", reason="teardown", allow_pruning=True)
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


class TestContinueAsNew:
    """continue_as_new must only fire from a clean idle point and only when enabled, and the
    loop state it carries must survive the hand-off."""

    def _idle_enabled_workflow(self, *, threshold: int = 0) -> ProcessTaskWorkflow:
        wf = ProcessTaskWorkflow()
        ctx = _build_context(github_integration_id=123)
        ctx.continue_as_new_enabled = True
        ctx.continue_as_new_history_threshold = threshold
        wf._context = ctx
        return wf

    async def test_agent_state_tracks_end_of_turn(self) -> None:
        workflow_instance = ProcessTaskWorkflow()

        await workflow_instance.agent_state_changed(True)
        assert workflow_instance._agent_active is True
        assert workflow_instance._end_of_turn_received is False

        await workflow_instance.agent_state_changed(False)
        assert (workflow_instance._agent_active, workflow_instance._end_of_turn_received) == (False, True)

    def test_build_and_restore_round_trips_loop_state(self, monkeypatch) -> None:
        chain_start = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
        monkeypatch.setattr(
            process_task_workflow_module.workflow, "info", Mock(return_value=Mock(start_time=chain_start))
        )
        wf = self._idle_enabled_workflow()
        wf._sandbox_url = "https://sandbox.example"
        wf._sandbox_connect_token = "tok"
        wf._ci_repetitions = 2
        wf._pr_fingerprint = "fp-1"
        wf._pr_progress_emitted = True
        wf._ci_resume_snapshot_created = True
        wf._first_user_message_received = True
        wf._is_agent_design_enabled = True
        wf._last_active_time = datetime(2026, 7, 16, 10, 30, tzinfo=UTC)
        wf._agent_active = False
        wf._end_of_turn_received = True
        wf._last_agent_heartbeat_at = datetime(2026, 7, 16, 10, 29, tzinfo=UTC)
        wf._sandbox_ttl_expires_at = datetime(2026, 7, 16, 15, 0, tzinfo=UTC)
        wf._slack_thread_context = {"channel": "C1"}
        wf._posthog_mcp_scopes = "full"

        resumed_input = wf._build_resumed_input(ProcessTaskInput(run_id="run-id", create_pr=False), sandbox_id="sb-1")

        assert resumed_input.prewarmed is False
        assert resumed_input.slack_thread_context == {"channel": "C1"}
        assert resumed_input.posthog_mcp_scopes == "full"
        rs = resumed_input.resumed_sandbox
        assert rs is not None
        assert (rs.sandbox_id, rs.sandbox_url, rs.connect_token) == ("sb-1", "https://sandbox.example", "tok")

        restored = ProcessTaskWorkflow()
        restored._restore_resumed_state(rs)

        assert restored._ci_repetitions == 2
        assert restored._pr_fingerprint == "fp-1"
        assert restored._pr_progress_emitted is True
        assert restored._ci_resume_snapshot_created is True
        assert restored._first_user_message_received is True
        assert restored._is_agent_design_enabled is True
        # The datetime survives the ISO round-trip.
        assert restored._last_active_time == datetime(2026, 7, 16, 10, 30, tzinfo=UTC)
        assert restored._agent_active is False
        assert restored._end_of_turn_received is True
        assert restored._last_agent_heartbeat_at == datetime(2026, 7, 16, 10, 29, tzinfo=UTC)
        assert restored._sandbox_ttl_expires_at == datetime(2026, 7, 16, 15, 0, tzinfo=UTC)
        # The wall-clock cap anchors on the chain start, so the first execution seeds it from
        # its own start_time and every later continuation carries that same value forward.
        assert restored._chain_started_at == chain_start
        assert restored._chain_start_time() == chain_start
        second_hop = restored._build_resumed_input(ProcessTaskInput(run_id="run-id"), sandbox_id="sb-2")
        assert second_hop.resumed_sandbox is not None
        assert second_hop.resumed_sandbox.chain_started_at == chain_start.isoformat()
        assert second_hop.resumed_sandbox.ci_resume_snapshot_created is True

    @parameterized.expand(
        [
            ("task_completed", lambda wf: setattr(wf, "_task_completed", True)),
            ("sandbox_gone", lambda wf: setattr(wf, "_sandbox_gone", True)),
            (
                "pending_followup",
                lambda wf: setattr(wf, "_pending_followup", PendingFollowup(message="m", artifact_ids=[])),
            ),
            (
                "pending_followups",
                lambda wf: wf._pending_followups.append(PendingFollowup(message="m", artifact_ids=[])),
            ),
            (
                "pending_permission",
                lambda wf: wf._pending_permission_responses.append(
                    PendingPermissionResponse(request_id="r", option_id="o", actor_user_id=1)
                ),
            ),
            ("heartbeat_pending", lambda wf: setattr(wf, "_heartbeat_received", True)),
            ("client_activity_pending", lambda wf: setattr(wf, "_client_activity_received", True)),
            ("slack_relay_active", lambda wf: setattr(wf, "_current_slack_relay_workflow_id", "relay-1")),
        ]
    )
    def test_does_not_continue_when_not_idle(self, _name: str, mutate) -> None:
        wf = self._idle_enabled_workflow(threshold=1)
        mutate(wf)
        # Each of these short-circuits before workflow.info(), so no workflow env is needed.
        assert wf._should_continue_as_new("sb-1") is False

    def test_does_not_continue_when_disabled(self) -> None:
        wf = self._idle_enabled_workflow(threshold=1)
        wf.context.continue_as_new_enabled = False
        assert wf._should_continue_as_new("sb-1") is False

    def test_does_not_continue_without_sandbox(self) -> None:
        wf = self._idle_enabled_workflow(threshold=1)
        assert wf._should_continue_as_new(None) is False

    def test_continues_when_history_over_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        wf = self._idle_enabled_workflow(threshold=100)
        fake_info = Mock()
        fake_info.get_current_history_length.return_value = 100
        fake_info.is_continue_as_new_suggested.return_value = False
        monkeypatch.setattr(process_task_workflow_module.workflow, "info", lambda: fake_info)
        assert wf._should_continue_as_new("sb-1") is True

    def test_continues_when_temporal_suggests(self, monkeypatch: pytest.MonkeyPatch) -> None:
        wf = self._idle_enabled_workflow(threshold=0)  # threshold off — fall back to the SDK signal
        fake_info = Mock()
        fake_info.is_continue_as_new_suggested.return_value = True
        monkeypatch.setattr(process_task_workflow_module.workflow, "info", lambda: fake_info)
        assert wf._should_continue_as_new("sb-1") is True
