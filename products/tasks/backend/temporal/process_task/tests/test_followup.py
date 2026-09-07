import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from temporalio import activity
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.tasks.backend.temporal.process_task.activities.create_resume_snapshot import (
    CreateResumeSnapshotInput,
    CreateResumeSnapshotOutput,
)
from products.tasks.backend.temporal.process_task.activities.emit_progress_activity import EmitProgressInput
from products.tasks.backend.temporal.process_task.activities.get_pr_context import GetPrContextOutput
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.provision_sandbox import (
    CreateSandboxForRepositoryOutput,
    PrepareSandboxForRepositoryOutput,
)
from products.tasks.backend.temporal.process_task.activities.record_peer_message_outcome import (
    RecordPeerMessageOutcomeInput,
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

_status_updates: list[tuple[str, str | None, bool]] = []


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
        state={"mode": "interactive"},
    )


@activity.defn(name="get_task_processing_context")
def _mock_get_context_background(_input) -> TaskProcessingContext:
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
    _status_updates.append((input.status, input.error_message, input.timed_out_inactivity))


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


_progress_events: list[tuple[str, str, str, str | None, str]] = []


@activity.defn(name="emit_progress_activity")
def _mock_emit_progress(input: EmitProgressInput) -> None:
    _progress_events.append((input.step, input.status, input.label, input.detail, input.group))


_peer_outcome_calls: list[tuple[str, str, str]] = []


@activity.defn(name="record_peer_message_outcome")
def _mock_record_peer_outcome(input: RecordPeerMessageOutcomeInput) -> bool:
    _peer_outcome_calls.append((input.peer_message_id, input.outcome, input.failure_phase))
    return True


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
    @pytest.mark.parametrize("message_id", ["msg-1", None])
    @pytest.mark.timeout(30, func_only=True)
    async def test_failed_interactive_followup_keeps_run_alive_and_surfaces_the_failure(self, message_id):
        _status_updates.clear()
        _progress_events.clear()

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
                    _mock_emit_progress,
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
                    # The inactivity exit time-skips hours past the failed delivery.
                    execution_timeout=timedelta(days=2),
                )

                # Let setup activities complete before signaling
                await asyncio.sleep(2)

                # A message_id is optional the whole way down: real user follow-ups
                # (thread comments, first activation message, signal-report replies) reach
                # this path with none, so the failure card must not hinge on one.
                signal_args = ["test followup", []]
                if message_id is not None:
                    signal_args.append(message_id)
                await handle.signal(ProcessTaskWorkflow.send_followup_message, args=signal_args)

                result = await handle.result()

        assert result.success is True

        assert [(s, e) for s, e, _ in _status_updates if s == "failed"] == []
        inactivity_exits = [(s, timed_out) for s, _, timed_out in _status_updates if timed_out]
        assert inactivity_exits == [("completed", True)]
        delivery_failures = [event for event in _progress_events if event[0] == "followup_delivery"]
        assert len(delivery_failures) == 1
        step, status, label, detail, group = delivery_failures[0]
        assert (step, status, label, detail) == (
            "followup_delivery",
            "failed",
            "Couldn't deliver your message",
            "RuntimeError: Sandbox session is dead",
        )
        if message_id is not None:
            assert group == f"followup-delivery:{message_id}:run-1"
        else:
            # No id to key on, so the run-id-scoped group carries a generated middle segment.
            assert group.startswith("followup-delivery:")
            assert group.endswith(":run-1")
            assert group != "followup-delivery::run-1"

    @pytest.mark.timeout(30, func_only=True)
    async def test_failed_background_followup_marks_run_as_failed_promptly(self):
        _status_updates.clear()
        _progress_events.clear()

        async with await WorkflowEnvironment.start_time_skipping() as env:
            task_queue = f"test-{uuid.uuid4()}"
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[ProcessTaskWorkflow],
                activities=[
                    _mock_get_context_background,
                    _mock_update_status,
                    _mock_prepare_sandbox,
                    _mock_create_sandbox,
                    _mock_clone_repository,
                    _mock_start_agent,
                    _mock_forward,
                    _mock_send_followup_raises,
                    _mock_emit_progress,
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
                    # The short timeout is the assertion: failing fast, not at the inactivity exit.
                    execution_timeout=timedelta(minutes=2),
                )

                # Let setup activities complete before signaling
                await asyncio.sleep(2)

                await handle.signal(ProcessTaskWorkflow.send_followup_message, "test followup")

                result = await handle.result()

        assert result.success is True

        failed_updates = [(s, e) for s, e, _ in _status_updates if s == "failed"]
        assert failed_updates == [("failed", "Follow-up delivery failed: RuntimeError: Sandbox session is dead")]
        assert [event for event in _progress_events if event[0] == "followup_delivery"] == []

    @pytest.mark.timeout(60, func_only=True)
    async def test_failed_peer_message_never_fails_the_recipient_run(self):
        # Delivery contract, item 1: the identical delivery failure that marks the
        # run failed for a user follow-up must, for a peer message, record the
        # outcome on the message row and leave the recipient run healthy.
        _status_updates.clear()
        _peer_outcome_calls.clear()
        peer_message_id = str(uuid.uuid4())

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
                    _mock_record_peer_outcome,
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
                    execution_timeout=timedelta(minutes=5),
                )

                await asyncio.sleep(2)

                await handle.signal(
                    ProcessTaskWorkflow.send_followup_message,
                    args=[
                        "peer ping",
                        [],
                        str(uuid.uuid4()),
                        None,
                        {"kind": "agent_peer_message", "peer_message_id": peer_message_id},
                    ],
                )

                # Advance VIRTUAL time until the recording activity fires: the
                # delivery activity's retry backoff runs on workflow timers, which
                # only progress under env.sleep in a time-skipping environment.
                for _ in range(60):
                    if _peer_outcome_calls:
                        break
                    await env.sleep(5)
                assert _peer_outcome_calls, "peer delivery failure was never recorded"

                await handle.signal(ProcessTaskWorkflow.complete_task, args=["completed", None])
                result = await handle.result()

        assert result.success is True
        assert _peer_outcome_calls == [(peer_message_id, "delivery_failed", "sandbox_delivery")]
        # The load-bearing assertion: the recipient run was never marked failed.
        assert [(s, e) for s, e, _ in _status_updates if s == "failed"] == []


_ci_context_overrides: dict = {}
_ci_followup_calls: list[str] = []
_pr_context_overrides: dict = {}
_snapshot_events: list[str] = []
_snapshot_failures_remaining = 0


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
        use_modal_resume_snapshots=_ci_context_overrides.get("use_modal_resume_snapshots", False),
        use_modal_directory_resume_snapshots=_ci_context_overrides.get("use_modal_directory_resume_snapshots", False),
        state=_ci_context_overrides.get("state"),
    )


@activity.defn(name="send_followup_to_sandbox")
def _mock_send_followup_records(input: SendFollowupToSandboxInput) -> None:
    if input.message is not None:
        _ci_followup_calls.append(input.message)
        _snapshot_events.append("followup")


@activity.defn(name="create_resume_snapshot")
def _mock_create_resume_snapshot(input: CreateResumeSnapshotInput) -> CreateResumeSnapshotOutput:
    global _snapshot_failures_remaining
    _snapshot_events.append(f"{input.reason}:{input.allow_pruning}")
    if input.reason == "ci_follow_up" and _snapshot_failures_remaining > 0:
        _snapshot_failures_remaining -= 1
        return CreateResumeSnapshotOutput(external_id=None, error="snapshot failed", duration_ms=10)
    return CreateResumeSnapshotOutput(
        external_id=f"snapshot-{len(_snapshot_events)}",
        snapshot_kind="directory",
        snapshot_mount_path="/tmp/workspace",
        duration_ms=10,
    )


@activity.defn(name="get_pr_context")
def _mock_get_pr_context(_input) -> GetPrContextOutput | None:
    # Defaults to failing CI: a fingerprint change alone no longer dispatches a
    # follow-up — only an actionable state (failing CI or a changes-requested
    # review) does. Overridable per test via the "ci_status" key.
    ci_status = _pr_context_overrides.get("ci_status", "failing")
    behavior = _pr_context_overrides.get("behavior", "changing")
    if behavior == "missing":
        _pr_context_overrides["_call_count"] = _pr_context_overrides.get("_call_count", 0) + 1
        return None
    if behavior == "closed":
        return GetPrContextOutput(
            pr_url="https://github.com/org/repo/pull/1",
            pr_state="closed",
            fingerprint="closed-fp",
            ci_status=ci_status,
        )
    if behavior == "unchanged":
        _pr_context_overrides["_call_count"] = _pr_context_overrides.get("_call_count", 0) + 1
        return GetPrContextOutput(
            pr_url="https://github.com/org/repo/pull/1",
            pr_state="open",
            fingerprint="stable-fp",
            ci_status=ci_status,
        )
    if behavior == "sequence":
        # Returns fingerprints from a configured list, repeating the last value
        # once exhausted. Lets a test deterministically drive change-vs-unchanged
        # transitions across CI ticks.
        sequence: list[str] = _pr_context_overrides["sequence"]
        idx = min(_pr_context_overrides.get("_call_count", 0), len(sequence) - 1)
        _pr_context_overrides["_call_count"] = idx + 1
        return GetPrContextOutput(
            pr_url="https://github.com/org/repo/pull/1",
            pr_state="open",
            fingerprint=sequence[idx],
            ci_status=ci_status,
        )
    # Default "changing": unique fingerprint per call so CI follow-up always fires
    _pr_context_overrides["_call_count"] = _pr_context_overrides.get("_call_count", 0) + 1
    return GetPrContextOutput(
        pr_url="https://github.com/org/repo/pull/1",
        pr_state="open",
        fingerprint=f"fp-{_pr_context_overrides['_call_count']}",
        ci_status=ci_status,
    )


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
            _mock_get_pr_context,
            _mock_create_resume_snapshot,
        ],
        workflow_runner=UnsandboxedWorkflowRunner(),
        activity_executor=ThreadPoolExecutor(max_workers=5),
    )


class TestCIFollowUpLoop:
    @pytest.fixture(autouse=True)
    def _reset_state(self):
        global _snapshot_failures_remaining
        _ci_context_overrides.clear()
        _ci_followup_calls.clear()
        _status_updates.clear()
        _pr_context_overrides.clear()
        _snapshot_events.clear()
        _snapshot_failures_remaining = 0
        yield
        _ci_context_overrides.clear()
        _ci_followup_calls.clear()
        _status_updates.clear()
        _pr_context_overrides.clear()
        _snapshot_events.clear()
        _snapshot_failures_remaining = 0

    @pytest.mark.timeout(60, func_only=True)
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
        timeout_updates = [(s, e) for s, e, timed_out in _status_updates if timed_out]
        assert timeout_updates, f"expected an inactivity-timeout completion, got {_status_updates}"
        assert timeout_updates == [("completed", None)]

    @pytest.mark.timeout(60, func_only=True)
    async def test_snapshots_idle_sandbox_before_ci_follow_up(self):
        global _snapshot_failures_remaining
        _ci_context_overrides["state"] = {"mode": "interactive"}
        _ci_context_overrides["use_modal_resume_snapshots"] = True
        _ci_context_overrides["use_modal_directory_resume_snapshots"] = True
        _pr_context_overrides["behavior"] = "unchanged"
        _snapshot_failures_remaining = 1

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
                await env.sleep(CI_FOLLOW_UP_DELAY.total_seconds() * 3 + 10)
                await handle.signal(ProcessTaskWorkflow.complete_task, args=["completed", None])
                await handle.result()

        assert _snapshot_events[0:2] == ["ci_follow_up:False", "followup"]
        assert _snapshot_events.count("ci_follow_up:False") == 2
        assert _snapshot_events[-1] == "teardown:True"

    @pytest.mark.timeout(60, func_only=True)
    async def test_refreshes_ci_snapshot_after_follow_up(self):
        _ci_context_overrides["state"] = {"mode": "interactive"}
        _ci_context_overrides["use_modal_resume_snapshots"] = True
        _ci_context_overrides["use_modal_directory_resume_snapshots"] = True
        _pr_context_overrides["behavior"] = "unchanged"

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
                for _ in range(5):
                    await env.sleep(CI_FOLLOW_UP_DELAY.total_seconds() + 10)
                    if "followup" in _snapshot_events:
                        followup_index = _snapshot_events.index("followup")
                        if "ci_follow_up:False" in _snapshot_events[followup_index + 1 :]:
                            break
                await handle.signal(ProcessTaskWorkflow.complete_task, args=["completed", None])
                await handle.result()

        followup_index = _snapshot_events.index("followup")
        assert "ci_follow_up:False" in _snapshot_events[followup_index + 1 :]
        assert _snapshot_events[-1] == "teardown:True"

    @pytest.mark.timeout(60, func_only=True)
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
    @pytest.mark.timeout(60, func_only=True)
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
                    execution_timeout=timedelta(hours=3),
                )
                # With CI gated off, the inactivity timer stays at its default
                # 2h and is not extended to cover CI_FOLLOW_UP_DELAY (15m). No
                # CI follow-up scheduler is armed, so the workflow terminates
                # via inactivity — which itself proves no follow-up could fire.
                await handle.result()

        assert _ci_followup_calls == []
        timeout_updates = [(s, e) for s, e, timed_out in _status_updates if timed_out]
        assert timeout_updates, f"expected an inactivity-timeout completion, got {_status_updates}"

    @pytest.mark.timeout(60, func_only=True)
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
        completed_updates = [(s, e) for s, e, _ in _status_updates if s == "completed" and e is None]
        assert len(completed_updates) >= 1

    @pytest.mark.timeout(90, func_only=True)
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
                await handle.signal(ProcessTaskWorkflow.heartbeat, arg=True)
                await env.sleep(60)
                followups_at_original_deadline = list(_ci_followup_calls)

                await env.sleep(CI_FOLLOW_UP_DELAY.total_seconds() + 60)
                await handle.signal(ProcessTaskWorkflow.complete_task, args=["completed", None])
                await handle.result()

        assert followups_at_original_deadline == [], (
            "heartbeat should have pushed the CI follow-up past the original 15m boundary"
        )
        assert _ci_followup_calls, "follow-up should still fire after the rescheduled deadline"

    @pytest.mark.timeout(90, func_only=True)
    async def test_idle_heartbeat_does_not_extend_ci_follow_up_clock(self):
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
                await handle.signal(ProcessTaskWorkflow.heartbeat)
                await env.sleep(60)
                followups_at_original_deadline = list(_ci_followup_calls)

                await handle.signal(ProcessTaskWorkflow.complete_task, args=["completed", None])
                await handle.result()

        assert followups_at_original_deadline, "idle heartbeat should not push the CI follow-up deadline"


class TestFollowupGuards:
    @pytest.fixture(autouse=True)
    def _reset_state(self):
        global _snapshot_failures_remaining
        _ci_context_overrides.clear()
        _ci_followup_calls.clear()
        _status_updates.clear()
        _pr_context_overrides.clear()
        _snapshot_events.clear()
        _snapshot_failures_remaining = 0
        yield
        _ci_context_overrides.clear()
        _ci_followup_calls.clear()
        _status_updates.clear()
        _pr_context_overrides.clear()
        _snapshot_events.clear()
        _snapshot_failures_remaining = 0

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

    @pytest.mark.timeout(60, func_only=True)
    async def test_skips_ci_follow_up_when_pr_context_missing(self):
        _pr_context_overrides["behavior"] = "missing"

        async with await WorkflowEnvironment.start_time_skipping() as env:
            task_queue = f"test-{uuid.uuid4()}"
            async with _make_worker(env, task_queue):
                handle = await env.client.start_workflow(
                    ProcessTaskWorkflow.run,
                    ProcessTaskInput(run_id="run-1"),
                    id=f"test-{uuid.uuid4()}",
                    task_queue=task_queue,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=timedelta(hours=3),
                )
                # The CI loop stops after finding no PR, then the workflow
                # exits via inactivity timeout — no signal needed.
                await handle.result()

        assert _ci_followup_calls == []

    @pytest.mark.timeout(60, func_only=True)
    async def test_skips_ci_follow_up_when_pr_is_closed(self):
        _pr_context_overrides["behavior"] = "closed"

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
                await env.sleep(CI_FOLLOW_UP_DELAY.total_seconds() * 2 + 60)
                await handle.signal(ProcessTaskWorkflow.complete_task, args=["completed", None])
                await handle.result()

        assert _ci_followup_calls == []

    async def test_skips_ci_follow_up_when_fingerprint_unchanged(self):
        # The first CI check runs (fingerprint moves from None → "stable-fp"),
        # sending a single follow-up. Subsequent checks must see the stored
        # fingerprint match and skip — so only one follow-up should ever be
        # dispatched, and get_pr_context must be called at most once per
        # CI_FOLLOW_UP_DELAY tick. If the skip path forgot to advance
        # _last_active_time, _wait_for_ci_follow_up would return immediately
        # on every loop iteration and burn the GitHub API rate limit.
        _pr_context_overrides["behavior"] = "unchanged"

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
                # Sleep well past the third CI deadline (45m+) so the skip
                # path is exercised twice. With the bug, _wait_for_ci_follow_up
                # returns instantly after each skip and the activity gets
                # called as fast as the round-trip allows; with the fix, each
                # skip resets _last_active_time and the next call is gated to
                # +CI_FOLLOW_UP_DELAY.
                await env.sleep(CI_FOLLOW_UP_DELAY.total_seconds() * 3 + 60)
                await handle.signal(ProcessTaskWorkflow.complete_task, args=["completed", None])
                await handle.result()

        assert len(_ci_followup_calls) == 1
        # One call per CI tick: fire at T=15m, skip at T=30m, skip at T=45m.
        # If _last_active_time isn't advanced on skip, _wait_for_ci_follow_up
        # returns immediately and the activity gets hammered.
        pr_context_calls = _pr_context_overrides.get("_call_count", 0)
        assert pr_context_calls <= 4, (
            f"expected ≤4 get_pr_context calls across 45m+, got {pr_context_calls} — "
            "skip path is tight-looping and burning the GitHub rate limit"
        )

    @pytest.mark.timeout(60, func_only=True)
    async def test_ci_follow_up_fires_on_changed_fingerprint_and_persists(self):
        # Once a follow-up fires for a new fingerprint, that fingerprint must
        # persist on the workflow so the *next* tick observing the same
        # fingerprint skips. Sequence drives CI to MAX_CI_REPETITIONS while
        # including an unchanged tick in the middle:
        #   tick 1: fp-A (vs None)  → fire        (persist fp-A)
        #   tick 2: fp-A (vs fp-A)  → skip        ← only succeeds if persisted
        #   tick 3: fp-B (vs fp-A)  → fire        (persist fp-B)
        #   tick 4: fp-C (vs fp-B)  → fire        (hits MAX, disables CI)
        # With broken persistence, tick 2 would also fire — MAX would be hit
        # one tick earlier and only 3 get_pr_context calls would land. The call
        # count is therefore the persistence signal.
        _pr_context_overrides["behavior"] = "sequence"
        _pr_context_overrides["sequence"] = ["fp-A", "fp-A", "fp-B", "fp-C"]

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
                # Workflow ends naturally via inactivity once MAX_CI_REPETITIONS
                # fires have happened — no signal needed.
                await handle.result()

        assert len(_ci_followup_calls) == MAX_CI_REPETITIONS
        assert all(msg == DEFAULT_CI_MESSAGE for msg in _ci_followup_calls)
        assert _pr_context_overrides.get("_call_count") == 4, (
            f"expected 4 get_pr_context calls (fire, skip, fire, fire) — broken persistence "
            f"would yield 3. Got {_pr_context_overrides.get('_call_count')}"
        )

    @pytest.mark.timeout(60, func_only=True)
    async def test_stops_ci_loop_when_no_pr_and_agent_idle(self):
        """When get_pr_context returns None and the agent is idle, the CI loop
        should stop after a single check instead of polling all 3 repetitions."""
        _pr_context_overrides["behavior"] = "missing"

        async with await WorkflowEnvironment.start_time_skipping() as env:
            task_queue = f"test-{uuid.uuid4()}"
            async with _make_worker(env, task_queue):
                handle = await env.client.start_workflow(
                    ProcessTaskWorkflow.run,
                    ProcessTaskInput(run_id="run-1"),
                    id=f"test-{uuid.uuid4()}",
                    task_queue=task_queue,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=timedelta(hours=3),
                )
                # No heartbeats sent — agent is idle. The CI loop should stop
                # after one check and the workflow exits via inactivity timeout.
                await handle.result()

        assert _ci_followup_calls == [], "no follow-up should be sent when no PR exists"
        assert _pr_context_overrides.get("_call_count") == 1, (
            f"expected exactly 1 get_pr_context call — loop should stop immediately after "
            f"discovering no PR. Got {_pr_context_overrides.get('_call_count')}"
        )
