import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from temporalio import activity
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.provision_sandbox import (
    CreateSandboxForRepositoryOutput,
    PrepareSandboxForRepositoryOutput,
)
from products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox import SendFollowupToSandboxInput
from products.tasks.backend.temporal.process_task.activities.start_agent_server import StartAgentServerOutput
from products.tasks.backend.temporal.process_task.activities.update_task_run_status import UpdateTaskRunStatusInput
from products.tasks.backend.temporal.process_task.workflow import (
    CI_FOLLOW_UP_DELAY,
    DEFAULT_CI_MESSAGE,
    MAX_CI_REPETITIONS,
    ProcessTaskInput,
    ProcessTaskWorkflow,
)

_status_updates: list[tuple[str, str | None]] = []


@activity.defn(name="get_task_processing_context")
def _mock_get_context(_input) -> TaskProcessingContext:
    return TaskProcessingContext(
        task_id="task-1",
        run_id="run-1",
        team_id=1,
        team_uuid=str(uuid.uuid4()),
        organization_id=str(uuid.uuid4()),
        github_integration_id=1,
        repository="org/repo",
        distinct_id="user-1",
    )


@activity.defn(name="update_task_run_status")
def _mock_update_status(input: UpdateTaskRunStatusInput) -> None:
    _status_updates.append((input.status, input.error_message))


@activity.defn(name="prepare_sandbox_for_repository")
def _mock_prepare_sandbox(_input) -> PrepareSandboxForRepositoryOutput:
    return PrepareSandboxForRepositoryOutput(
        sandbox_name="sandbox-name",
        repository="org/repo",
        github_token="",
        branch=None,
        environment_variables={},
        snapshot_id=None,
        snapshot_external_id=None,
        used_snapshot=False,
        should_create_snapshot=False,
        shallow_clone=True,
        image_source="base_image",
        image_source_label="published sandbox base image",
    )


@activity.defn(name="create_sandbox_for_repository")
def _mock_create_sandbox(_input) -> CreateSandboxForRepositoryOutput:
    return CreateSandboxForRepositoryOutput(
        sandbox_id="sb-1",
        sandbox_url="http://localhost",
        connect_token=None,
    )


@activity.defn(name="clone_repository_in_sandbox")
def _mock_clone_repository(_input) -> None:
    pass


@activity.defn(name="start_agent_server")
def _mock_start_agent(_input) -> StartAgentServerOutput:
    return StartAgentServerOutput(sandbox_url="http://localhost")


@activity.defn(name="forward_pending_user_message")
def _mock_forward(_input) -> None:
    pass


@activity.defn(name="send_followup_to_sandbox")
def _mock_send_followup_raises(_input) -> None:
    raise RuntimeError("Sandbox session is dead")


@activity.defn(name="track_workflow_event")
def _mock_track(_input) -> None:
    pass


@activity.defn(name="read_sandbox_logs")
def _mock_read_logs(_input) -> str:
    return ""


@activity.defn(name="cleanup_sandbox")
def _mock_cleanup(_input) -> None:
    pass


pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


class TestFollowupDeliveryFailure:
    @pytest.mark.timeout(30)
    async def test_failed_followup_marks_run_as_failed_promptly(self):
        """The workflow must exit its main loop and mark the run as failed
        within seconds when a followup delivery fails — not after the
        5-minute inactivity timeout."""
        _status_updates.clear()

        async with await WorkflowEnvironment.start_time_skipping() as env:
            task_queue = f"test-{uuid.uuid4()}"
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[ProcessTaskWorkflow],
                activities=[
                    _mock_get_context,
                    _mock_update_status,
                    _mock_prepare_sandbox,
                    _mock_create_sandbox,
                    _mock_clone_repository,
                    _mock_start_agent,
                    _mock_forward,
                    _mock_send_followup_raises,
                    _mock_track,
                    _mock_read_logs,
                    _mock_cleanup,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=5),
            ):
                handle = await env.client.start_workflow(
                    ProcessTaskWorkflow.run,
                    ProcessTaskInput(run_id="run-1"),
                    id=f"test-{uuid.uuid4()}",
                    task_queue=task_queue,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=timedelta(minutes=2),
                )

                # Let setup activities complete before signaling
                await asyncio.sleep(2)

                await handle.signal(ProcessTaskWorkflow.send_followup_message, "test followup")

                result = await handle.result()

        assert result.success is True

        failed_updates = [(s, e) for s, e in _status_updates if s == "failed"]
        assert len(failed_updates) == 1
        assert "Follow-up delivery failed" in (failed_updates[0][1] or "")


_ci_context_overrides: dict = {}
_ci_followup_calls: list[str] = []


@activity.defn(name="get_task_processing_context")
def _mock_get_context_configurable(_input) -> TaskProcessingContext:
    return TaskProcessingContext(
        task_id="task-1",
        run_id="run-1",
        team_id=1,
        team_uuid=str(uuid.uuid4()),
        organization_id=str(uuid.uuid4()),
        github_integration_id=1,
        repository="org/repo",
        distinct_id="user-1",
        create_pr=_ci_context_overrides.get("create_pr", True),
        pr_loop_enabled=_ci_context_overrides.get("pr_loop_enabled", True),
        ci_prompt=_ci_context_overrides.get("ci_prompt"),
    )


@activity.defn(name="send_followup_to_sandbox")
def _mock_send_followup_records(input: SendFollowupToSandboxInput) -> None:
    if input.message is not None:
        _ci_followup_calls.append(input.message)


def _make_worker(env, task_queue: str) -> Worker:
    return Worker(
        env.client,
        task_queue=task_queue,
        workflows=[ProcessTaskWorkflow],
        activities=[
            _mock_get_context_configurable,
            _mock_update_status,
            _mock_prepare_sandbox,
            _mock_create_sandbox,
            _mock_clone_repository,
            _mock_start_agent,
            _mock_forward,
            _mock_send_followup_records,
            _mock_track,
            _mock_read_logs,
            _mock_cleanup,
        ],
        workflow_runner=UnsandboxedWorkflowRunner(),
        activity_executor=ThreadPoolExecutor(max_workers=5),
    )


class TestCIFollowUpLoop:
    @pytest.fixture(autouse=True)
    def _reset_state(self):
        _ci_context_overrides.clear()
        _ci_followup_calls.clear()
        _status_updates.clear()
        yield
        _ci_context_overrides.clear()
        _ci_followup_calls.clear()
        _status_updates.clear()

    @pytest.mark.timeout(60)
    async def test_runs_to_inactivity_timeout_after_max_ci_repetitions(self):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            task_queue = f"test-{uuid.uuid4()}"
            async with _make_worker(env, task_queue):
                handle = await env.client.start_workflow(
                    ProcessTaskWorkflow.run,
                    ProcessTaskInput(run_id="run-1"),
                    id=f"test-{uuid.uuid4()}",
                    task_queue=task_queue,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=timedelta(hours=4),
                )
                result = await handle.result()

        assert result.success is True
        assert len(_ci_followup_calls) == MAX_CI_REPETITIONS
        assert all(msg == DEFAULT_CI_MESSAGE for msg in _ci_followup_calls)
        timeout_updates = [(s, e) for s, e in _status_updates if "timed out" in (e or "")]
        assert timeout_updates, f"expected an inactivity-timeout completion, got {_status_updates}"

    @pytest.mark.timeout(60)
    async def test_uses_ci_prompt_override_when_set(self):
        custom_prompt = "Custom CI prompt: please re-run the failed unit tests."
        _ci_context_overrides["ci_prompt"] = custom_prompt

        async with await WorkflowEnvironment.start_time_skipping() as env:
            task_queue = f"test-{uuid.uuid4()}"
            async with _make_worker(env, task_queue):
                handle = await env.client.start_workflow(
                    ProcessTaskWorkflow.run,
                    ProcessTaskInput(run_id="run-1"),
                    id=f"test-{uuid.uuid4()}",
                    task_queue=task_queue,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=timedelta(hours=4),
                )
                await env.sleep(CI_FOLLOW_UP_DELAY.total_seconds() + 10)
                await handle.signal(ProcessTaskWorkflow.complete_task, args=["completed", None])
                await handle.result()

        assert _ci_followup_calls
        assert all(msg == custom_prompt for msg in _ci_followup_calls)

    @pytest.mark.parametrize(
        "create_pr, pr_loop_enabled",
        [
            (True, False),
            (False, True),
            (False, False),
        ],
    )
    @pytest.mark.timeout(60)
    async def test_no_ci_follow_up_when_gated_off(self, create_pr: bool, pr_loop_enabled: bool):
        _ci_context_overrides["create_pr"] = create_pr
        _ci_context_overrides["pr_loop_enabled"] = pr_loop_enabled

        async with await WorkflowEnvironment.start_time_skipping() as env:
            task_queue = f"test-{uuid.uuid4()}"
            async with _make_worker(env, task_queue):
                handle = await env.client.start_workflow(
                    ProcessTaskWorkflow.run,
                    ProcessTaskInput(run_id="run-1"),
                    id=f"test-{uuid.uuid4()}",
                    task_queue=task_queue,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=timedelta(hours=2),
                )
                await env.sleep(CI_FOLLOW_UP_DELAY.total_seconds() + 60)
                await handle.signal(ProcessTaskWorkflow.complete_task, args=["completed", None])
                await handle.result()

        assert _ci_followup_calls == []

    @pytest.mark.timeout(60)
    async def test_completion_signal_wins_over_ready_ci_follow_up(self):
        # Advance virtual time to just before the 15m CI deadline, then fire
        # the completion signal. The armed CI timer must be cancelled and no
        # follow-up message sent — the workflow should terminate cleanly.
        async with await WorkflowEnvironment.start_time_skipping() as env:
            task_queue = f"test-{uuid.uuid4()}"
            async with _make_worker(env, task_queue):
                handle = await env.client.start_workflow(
                    ProcessTaskWorkflow.run,
                    ProcessTaskInput(run_id="run-1"),
                    id=f"test-{uuid.uuid4()}",
                    task_queue=task_queue,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=timedelta(hours=1),
                )
                await env.sleep(CI_FOLLOW_UP_DELAY.total_seconds() - 5)
                await handle.signal(ProcessTaskWorkflow.complete_task, args=["completed", None])
                result = await handle.result()

        assert result.success is True
        assert _ci_followup_calls == []
        completed_updates = [(s, e) for s, e in _status_updates if s == "completed" and e is None]
        assert len(completed_updates) >= 1

    @pytest.mark.timeout(90)
    async def test_heartbeat_with_agent_active_extends_ci_follow_up_clock(self):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            task_queue = f"test-{uuid.uuid4()}"
            async with _make_worker(env, task_queue):
                handle = await env.client.start_workflow(
                    ProcessTaskWorkflow.run,
                    ProcessTaskInput(run_id="run-1"),
                    id=f"test-{uuid.uuid4()}",
                    task_queue=task_queue,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=timedelta(hours=2),
                )
                near_delay = CI_FOLLOW_UP_DELAY.total_seconds() - 30
                await env.sleep(near_delay)
                await handle.signal(ProcessTaskWorkflow.heartbeat, args=[True])
                await env.sleep(60)
                followups_at_original_deadline = list(_ci_followup_calls)

                await env.sleep(CI_FOLLOW_UP_DELAY.total_seconds() + 60)
                await handle.signal(ProcessTaskWorkflow.complete_task, args=["completed", None])
                await handle.result()

        assert followups_at_original_deadline == [], (
            "heartbeat(agent_active=True) should have pushed the CI follow-up past the original 15m boundary"
        )
        assert _ci_followup_calls, "follow-up should still fire after the rescheduled deadline"


class TestFollowupGuards:
    @pytest.mark.parametrize(
        "message,artifact_ids,expected",
        [
            (None, [], True),
            ("", [], True),
            (None, ["artifact-1"], False),
            ("message", [], False),
            ("message", ["artifact-1"], False),
        ],
    )
    def test_should_skip_followup(self, message: str | None, artifact_ids: list[str], expected: bool):
        assert ProcessTaskWorkflow._should_skip_followup(message, artifact_ids) is expected
