from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import AsyncMock, Mock

from products.tasks.backend.temporal.constants import (
    ACK_TIMEOUT,
    DEFAULT_CI_MESSAGE,
    HEARTBEAT_DEBOUNCE,
    MAX_ACK_RETRIES,
    MAX_CI_REPETITIONS,
)
from products.tasks.backend.temporal.execute_sandbox.workflow import PARENT_ATTACHED_SIGNAL, ChildCompletionPayload
from products.tasks.backend.temporal.process_task.activities.get_pr_context import GetPrContextOutput, get_pr_context
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.task_management import workflow as task_management_workflow_module
from products.tasks.backend.temporal.task_management.workflow import (
    ChildAck,
    ChildCompletion,
    CIFollowUpDecision,
    PendingAckSlot,
    PendingExternalFollowup,
    TaskManagementWorkflow,
    TaskRunManagementInput,
)


def _build_context(
    *,
    create_pr: bool = True,
    pr_loop_enabled: bool = True,
    ci_prompt: str | None = None,
) -> TaskProcessingContext:
    return TaskProcessingContext(
        task_id="task-id",
        run_id="run-id",
        team_id=1,
        team_uuid="team-uuid",
        organization_id="organization-id",
        github_integration_id=123,
        repository="org/repo",
        distinct_id="distinct-id",
        create_pr=create_pr,
        pr_loop_enabled=pr_loop_enabled,
        ci_prompt=ci_prompt,
    )


@pytest.fixture
def silent_workflow_logger(monkeypatch):
    logger = Mock()
    monkeypatch.setattr(task_management_workflow_module.workflow, "logger", logger)
    return logger


@pytest.fixture
def fixed_now(monkeypatch):
    """Pin `workflow.now()` to a configurable instant.

    Returns a mutable holder so tests can advance virtual time without
    actually waiting. We monkeypatch the symbol on the module-level
    `workflow` shim that the orchestrator imported.
    """

    class Clock:
        def __init__(self) -> None:
            self.now = datetime(2026, 5, 19, 12, 0, 0, tzinfo=UTC)

        def advance(self, delta: timedelta) -> None:
            self.now = self.now + delta

    clock = Clock()
    monkeypatch.setattr(task_management_workflow_module.workflow, "now", lambda: clock.now)
    return clock


class TestParseInputs:
    def test_parses_required_and_optional_fields(self):
        raw = '{"run_id":"r","create_pr":false,"slack_thread_context":{"channel":"C1"},"posthog_mcp_scopes":"full"}'
        parsed = TaskManagementWorkflow.parse_inputs([raw])
        assert parsed == TaskRunManagementInput(
            run_id="r",
            create_pr=False,
            slack_thread_context={"channel": "C1"},
            posthog_mcp_scopes="full",
        )

    def test_applies_defaults(self):
        parsed = TaskManagementWorkflow.parse_inputs(['{"run_id":"r"}'])
        assert parsed.create_pr is True
        assert parsed.slack_thread_context is None
        assert parsed.posthog_mcp_scopes == "read_only"


class TestExternalSignalHandlers:
    async def test_complete_task_stashes_pending_completion(self):
        workflow = TaskManagementWorkflow()
        await workflow.complete_task("failed", "boom")
        assert workflow._pending_external_complete == ("failed", "boom")

    async def test_send_followup_message_queues_with_user_source(self):
        workflow = TaskManagementWorkflow()
        await workflow.send_followup_message("hello", ["a1"])
        assert workflow._pending_external_followups == [
            PendingExternalFollowup(message="hello", artifact_ids=["a1"], source="user")
        ]

    async def test_send_followup_message_handles_none_artifact_ids(self):
        workflow = TaskManagementWorkflow()
        await workflow.send_followup_message("hello")
        assert workflow._pending_external_followups == [
            PendingExternalFollowup(message="hello", artifact_ids=[], source="user")
        ]

    async def test_external_heartbeat_records_activity(self, fixed_now):
        # Heartbeats only flow child -> parent, so the external handler is a
        # local-state-only update — it never forwards down to the sandbox.
        workflow = TaskManagementWorkflow()
        await workflow.heartbeat(agent_active=True)
        assert workflow._heartbeat_received is True
        assert workflow._last_active_time == fixed_now.now

    async def test_external_heartbeat_does_not_forward_to_alive_sandbox(self, monkeypatch, fixed_now):
        # Even with a live sandbox, external heartbeats stay local. The
        # child's own relay activity is the authoritative source for
        # bumping the sandbox's inactivity timer.
        workflow = TaskManagementWorkflow()
        workflow._run_id = "run-id"
        workflow._sandbox_workflow_id = "sandbox-wf"
        workflow._sandbox_alive = True

        handle = Mock()
        handle.signal = AsyncMock()
        get_handle = Mock(return_value=handle)
        monkeypatch.setattr(
            task_management_workflow_module.workflow,
            "get_external_workflow_handle",
            get_handle,
        )

        await workflow.heartbeat(agent_active=True)

        get_handle.assert_not_called()
        handle.signal.assert_not_awaited()
        assert workflow._heartbeat_received is True


class TestChildFacingSignalHandlers:
    async def test_on_child_ack_appends_to_queue(self, fixed_now):
        workflow = TaskManagementWorkflow()
        await workflow.on_child_ack("send_followup_message", "ack-1", accepted=False, detail="empty")

        assert workflow._child_acks == [
            ChildAck(
                signal_name="send_followup_message",
                ack_id="ack-1",
                accepted=False,
                detail="empty",
                received_at=fixed_now.now,
            )
        ]

    async def test_on_child_heartbeat_records_activity(self, fixed_now):
        workflow = TaskManagementWorkflow()
        await workflow.on_child_heartbeat(agent_active=True)
        assert workflow._heartbeat_received is True
        assert workflow._last_active_time == fixed_now.now

    async def test_on_child_completed_records_completion(self):
        workflow = TaskManagementWorkflow()
        await workflow.on_child_completed(
            ChildCompletionPayload(success=False, error="boom", sandbox_id="sb-1", timed_out=True)
        )

        assert workflow._child_completion == ChildCompletion(
            success=False,
            error="boom",
            sandbox_id="sb-1",
            timed_out=True,
        )

    async def test_on_child_completed_first_report_wins(self):
        # Duplicate completions can land on replay or after retries — the
        # first non-None completion is the source of truth.
        workflow = TaskManagementWorkflow()
        await workflow.on_child_completed(ChildCompletionPayload(success=True, sandbox_id="sb-1"))
        await workflow.on_child_completed(ChildCompletionPayload(success=False, error="late", sandbox_id="sb-1"))

        assert workflow._child_completion is not None
        assert workflow._child_completion.success is True
        assert workflow._child_completion.error is None


class TestRecordHeartbeat:
    def test_inactive_heartbeat_sets_flag_only(self, fixed_now):
        workflow = TaskManagementWorkflow()
        workflow._record_heartbeat(agent_active=False)
        assert workflow._heartbeat_received is True
        assert workflow._last_active_time is None

    def test_first_active_heartbeat_sets_last_active(self, fixed_now):
        workflow = TaskManagementWorkflow()
        workflow._record_heartbeat(agent_active=True)
        assert workflow._last_active_time == fixed_now.now

    def test_active_heartbeat_within_debounce_window_does_not_advance(self, fixed_now):
        # A torrent of heartbeats arrives faster than the debounce window;
        # _last_active_time should not be re-stamped each time, or CI timing
        # ends up dependent on the jitter of relay frequency.
        workflow = TaskManagementWorkflow()
        workflow._record_heartbeat(agent_active=True)
        first = workflow._last_active_time

        fixed_now.advance(HEARTBEAT_DEBOUNCE - timedelta(seconds=1))
        workflow._record_heartbeat(agent_active=True)

        assert workflow._last_active_time == first

    def test_active_heartbeat_past_debounce_window_advances(self, fixed_now):
        workflow = TaskManagementWorkflow()
        workflow._record_heartbeat(agent_active=True)

        fixed_now.advance(HEARTBEAT_DEBOUNCE + timedelta(seconds=1))
        workflow._record_heartbeat(agent_active=True)

        assert workflow._last_active_time == fixed_now.now


class TestCIFollowUpEnabled:
    def test_disabled_when_context_unset(self):
        workflow = TaskManagementWorkflow()
        assert workflow._ci_follow_up_enabled() is False

    @pytest.mark.parametrize(
        "create_pr,pr_loop_enabled,expected",
        [
            (True, True, True),
            (False, True, False),
            (True, False, False),
            (False, False, False),
        ],
    )
    def test_gated_by_context_flags(self, create_pr: bool, pr_loop_enabled: bool, expected: bool):
        workflow = TaskManagementWorkflow()
        workflow._context = _build_context(create_pr=create_pr, pr_loop_enabled=pr_loop_enabled)
        assert workflow._ci_follow_up_enabled() is expected

    def test_disabled_once_max_repetitions_reached(self):
        workflow = TaskManagementWorkflow()
        workflow._context = _build_context()
        workflow._ci_repetitions = MAX_CI_REPETITIONS
        assert workflow._ci_follow_up_enabled() is False


class TestShouldRunCIFollowUp:
    async def test_returns_no_pr_when_pr_context_missing(self, monkeypatch):
        workflow = TaskManagementWorkflow()
        workflow._context = _build_context()

        async def fake_execute_activity(activity_fn, *args, **kwargs):
            assert activity_fn is get_pr_context
            return None

        monkeypatch.setattr(task_management_workflow_module.workflow, "execute_activity", fake_execute_activity)

        decision = await workflow._should_run_ci_follow_up()
        assert decision is CIFollowUpDecision.NO_PR

    async def test_returns_skip_when_pr_closed(self, monkeypatch, silent_workflow_logger):
        workflow = TaskManagementWorkflow()
        workflow._context = _build_context()

        async def fake_execute_activity(activity_fn, *args, **kwargs):
            return GetPrContextOutput(
                pr_url="https://github.com/org/repo/pull/1",
                pr_state="closed",
                fingerprint="closed-fp",
            )

        monkeypatch.setattr(task_management_workflow_module.workflow, "execute_activity", fake_execute_activity)

        decision = await workflow._should_run_ci_follow_up()
        assert decision is CIFollowUpDecision.SKIP

    async def test_returns_fire_when_fingerprint_changes_and_persists_it(self, monkeypatch, silent_workflow_logger):
        workflow = TaskManagementWorkflow()
        workflow._context = _build_context()

        async def fake_execute_activity(activity_fn, *args, **kwargs):
            return GetPrContextOutput(
                pr_url="https://github.com/org/repo/pull/1",
                pr_state="open",
                fingerprint="fp-1",
            )

        monkeypatch.setattr(task_management_workflow_module.workflow, "execute_activity", fake_execute_activity)

        decision = await workflow._should_run_ci_follow_up()

        assert decision is CIFollowUpDecision.FIRE
        # Fingerprint must persist so the next tick with the same fp returns SKIP.
        assert workflow._pr_fingerprint == "fp-1"

    async def test_returns_skip_when_fingerprint_unchanged(self, monkeypatch, silent_workflow_logger):
        workflow = TaskManagementWorkflow()
        workflow._context = _build_context()
        workflow._pr_fingerprint = "fp-1"

        async def fake_execute_activity(activity_fn, *args, **kwargs):
            return GetPrContextOutput(
                pr_url="https://github.com/org/repo/pull/1",
                pr_state="open",
                fingerprint="fp-1",
            )

        monkeypatch.setattr(task_management_workflow_module.workflow, "execute_activity", fake_execute_activity)

        decision = await workflow._should_run_ci_follow_up()
        assert decision is CIFollowUpDecision.SKIP


class TestMaybeDispatchCIFollowUp:
    async def test_fire_dispatches_and_increments_repetitions(self, monkeypatch, fixed_now):
        # `_dispatch_ci_follow_up` increments repetitions, sets last_active so
        # _wait_for_ci_follow_up sleeps a full window, and forwards via the
        # signal-child-followup machinery.
        workflow = TaskManagementWorkflow()
        workflow._context = _build_context(ci_prompt="custom prompt")
        workflow._run_id = "run-id"
        workflow._sandbox_workflow_id = "sandbox-wf"

        monkeypatch.setattr(workflow, "_should_run_ci_follow_up", AsyncMock(return_value=CIFollowUpDecision.FIRE))
        signal_mock = AsyncMock()
        monkeypatch.setattr(workflow, "_signal_child_followup", signal_mock)

        await workflow._maybe_dispatch_ci_follow_up()

        assert workflow._ci_repetitions == 1
        assert workflow._last_active_time == fixed_now.now
        signal_mock.assert_awaited_once_with(message="custom prompt", artifact_ids=[], source="ci")

    async def test_fire_falls_back_to_default_ci_message(self, monkeypatch, fixed_now):
        workflow = TaskManagementWorkflow()
        workflow._context = _build_context(ci_prompt=None)
        workflow._run_id = "run-id"

        monkeypatch.setattr(workflow, "_should_run_ci_follow_up", AsyncMock(return_value=CIFollowUpDecision.FIRE))
        signal_mock = AsyncMock()
        monkeypatch.setattr(workflow, "_signal_child_followup", signal_mock)

        await workflow._maybe_dispatch_ci_follow_up()

        signal_mock.assert_awaited_once_with(message=DEFAULT_CI_MESSAGE, artifact_ids=[], source="ci")

    async def test_no_pr_disables_ci_loop(self, monkeypatch, silent_workflow_logger):
        # No PR → there will never be one; we have to disable the loop entirely
        # or the CI timer branch would keep waking up the orchestrator.
        workflow = TaskManagementWorkflow()
        workflow._context = _build_context()
        workflow._run_id = "run-id"

        monkeypatch.setattr(workflow, "_should_run_ci_follow_up", AsyncMock(return_value=CIFollowUpDecision.NO_PR))
        signal_mock = AsyncMock()
        monkeypatch.setattr(workflow, "_signal_child_followup", signal_mock)

        await workflow._maybe_dispatch_ci_follow_up()

        assert workflow._ci_repetitions == MAX_CI_REPETITIONS
        signal_mock.assert_not_awaited()

    async def test_skip_advances_last_active_to_bound_next_check(self, monkeypatch, fixed_now):
        # When a check skips (PR unchanged or closed), we must reset
        # _last_active_time so the next _wait_for_ci_follow_up sleeps a full
        # CI_FOLLOW_UP_DELAY instead of returning immediately and tight-
        # looping the GitHub API.
        workflow = TaskManagementWorkflow()
        workflow._context = _build_context()
        workflow._run_id = "run-id"

        monkeypatch.setattr(workflow, "_should_run_ci_follow_up", AsyncMock(return_value=CIFollowUpDecision.SKIP))
        signal_mock = AsyncMock()
        monkeypatch.setattr(workflow, "_signal_child_followup", signal_mock)

        await workflow._maybe_dispatch_ci_follow_up()

        assert workflow._last_active_time == fixed_now.now
        signal_mock.assert_not_awaited()
        # Skip should not consume a repetition — that's reserved for actual fires.
        assert workflow._ci_repetitions == 0


class TestDrainExternalSignals:
    async def test_followups_drained_before_completion(self, monkeypatch):
        # complete_task is terminal for a session — if we processed it first,
        # any pending follow-up messages would be dropped on the floor.
        workflow = TaskManagementWorkflow()
        workflow._run_id = "run-id"
        workflow._sandbox_workflow_id = "sandbox-wf"
        workflow._sandbox_alive = True  # sandbox running → no re-bootstrap
        workflow._pending_external_followups.extend(
            [
                PendingExternalFollowup(message="m1", artifact_ids=[], source="user"),
                PendingExternalFollowup(message="m2", artifact_ids=["a"], source="user"),
            ]
        )
        workflow._pending_external_complete = ("completed", None)

        call_order: list[str] = []
        followup_mock = AsyncMock(side_effect=lambda **kw: call_order.append(f"followup:{kw['message']}"))
        complete_mock = AsyncMock(side_effect=lambda *a, **kw: call_order.append(f"complete:{a[0]}"))
        monkeypatch.setattr(workflow, "_signal_child_followup", followup_mock)
        monkeypatch.setattr(workflow, "_signal_child_complete", complete_mock)
        monkeypatch.setattr(workflow, "_persist_pending_followups", AsyncMock())

        await workflow._drain_external_signals()

        assert call_order == ["followup:m1", "followup:m2", "complete:completed"]
        assert workflow._pending_external_followups == []
        assert workflow._pending_external_complete is None

    async def test_rebootstrap_when_sandbox_dead_and_followups_pending(self, monkeypatch, silent_workflow_logger):
        # The defining property of the persistent-orchestrator model: a
        # follow-up arriving after a sandbox session ended must lazily
        # bootstrap a new sandbox rather than getting dropped.
        workflow = TaskManagementWorkflow()
        workflow._run_id = "run-id"
        workflow._sandbox_workflow_id = "sandbox-wf"
        workflow._sandbox_alive = False
        workflow._pending_external_followups.append(
            PendingExternalFollowup(message="resume", artifact_ids=[], source="user")
        )

        bootstrap_mock = AsyncMock()
        monkeypatch.setattr(workflow, "_ensure_sandbox_workflow_started", bootstrap_mock)
        monkeypatch.setattr(workflow, "_signal_child_followup", AsyncMock())
        monkeypatch.setattr(workflow, "_persist_pending_followups", AsyncMock())

        await workflow._drain_external_signals()

        bootstrap_mock.assert_awaited_once()

    async def test_complete_dropped_when_sandbox_dead_with_no_followups(self, monkeypatch, silent_workflow_logger):
        # complete_task without follow-ups is meaningless when the sandbox is
        # gone — re-bootstrapping just to immediately tell the new sandbox to
        # complete would be wasteful. Drop and log.
        workflow = TaskManagementWorkflow()
        workflow._run_id = "run-id"
        workflow._sandbox_workflow_id = "sandbox-wf"
        workflow._sandbox_alive = False
        workflow._pending_external_complete = ("completed", None)

        bootstrap_mock = AsyncMock()
        complete_mock = AsyncMock()
        monkeypatch.setattr(workflow, "_ensure_sandbox_workflow_started", bootstrap_mock)
        monkeypatch.setattr(workflow, "_signal_child_complete", complete_mock)
        monkeypatch.setattr(workflow, "_persist_pending_followups", AsyncMock())

        await workflow._drain_external_signals()

        bootstrap_mock.assert_not_awaited()
        complete_mock.assert_not_awaited()
        assert workflow._pending_external_complete is None


class TestDrainChildSignals:
    async def test_matched_ack_clears_slot_and_logs(self, fixed_now, silent_workflow_logger):
        workflow = TaskManagementWorkflow()
        workflow._run_id = "run-id"
        workflow._pending_ack_slots["ack-1"] = PendingAckSlot(
            signal_name="send_followup_message", sent_at=fixed_now.now
        )
        workflow._child_acks.append(
            ChildAck(
                signal_name="send_followup_message",
                ack_id="ack-1",
                accepted=True,
                detail=None,
                received_at=fixed_now.now,
            )
        )

        await workflow._drain_child_signals()

        assert workflow._pending_ack_slots == {}
        assert workflow._child_acks == []
        # Heartbeat flag is reset every drain so the wait condition can fire again.
        assert workflow._heartbeat_received is False
        silent_workflow_logger.info.assert_called()

    async def test_unmatched_ack_is_logged_at_debug_and_does_not_raise(self, fixed_now, silent_workflow_logger):
        # ACKs without a slot can happen if a slot was already cleared by
        # another path. They must not crash the orchestrator.
        workflow = TaskManagementWorkflow()
        workflow._run_id = "run-id"
        workflow._child_acks.append(
            ChildAck(
                signal_name="send_followup_message",
                ack_id="unknown-ack",
                accepted=True,
                detail=None,
                received_at=fixed_now.now,
            )
        )

        await workflow._drain_child_signals()

        assert workflow._child_acks == []
        silent_workflow_logger.debug.assert_called()


class TestSignalChildFollowup:
    async def test_signals_external_handle_with_ack_id(self, monkeypatch, fixed_now):
        workflow = TaskManagementWorkflow()
        workflow._run_id = "run-id"
        workflow._sandbox_workflow_id = "sandbox-wf"

        handle = Mock()
        handle.signal = AsyncMock()
        monkeypatch.setattr(
            task_management_workflow_module.workflow,
            "get_external_workflow_handle",
            Mock(return_value=handle),
        )
        monkeypatch.setattr(task_management_workflow_module.workflow, "uuid4", lambda: "ack-generated")

        await workflow._signal_child_followup(message="m", artifact_ids=["a"], source="ci")

        handle.signal.assert_awaited_once_with(
            "send_followup_message",
            args=["ack-generated", "m", ["a"], "ci"],
        )
        slot = workflow._pending_ack_slots["ack-generated"]
        assert slot.signal_name == "send_followup_message"
        # signal_args must mirror the exact bytes we sent so the retry loop
        # can replay them — the child dedupes on ack_id so a replay is safe.
        assert slot.signal_args == ["ack-generated", "m", ["a"], "ci"]

    async def test_skips_when_no_sandbox_id(self, monkeypatch, silent_workflow_logger):
        # If the sandbox workflow id was never set we have nowhere to deliver
        # to. Logging is the only side-effect.
        workflow = TaskManagementWorkflow()
        workflow._run_id = "run-id"
        get_handle = Mock()
        monkeypatch.setattr(task_management_workflow_module.workflow, "get_external_workflow_handle", get_handle)

        await workflow._signal_child_followup(message="m", artifact_ids=[], source="user")

        get_handle.assert_not_called()
        assert workflow._pending_ack_slots == {}

    async def test_keeps_slot_on_signal_failure_for_retry(self, monkeypatch, fixed_now, silent_workflow_logger):
        # The slot stays in place even when the initial signal send fails.
        # The retry loop (`_retry_stale_acks`) will re-attempt after
        # ACK_TIMEOUT — keeping the slot is how the "child unreachable, parent
        # retries" branch of the design actually works. signal_args is recorded
        # so the retry can re-send identical bytes (the child dedupes by ack_id).
        workflow = TaskManagementWorkflow()
        workflow._run_id = "run-id"
        workflow._sandbox_workflow_id = "sandbox-wf"

        handle = Mock()
        handle.signal = AsyncMock(side_effect=RuntimeError("child unreachable"))
        monkeypatch.setattr(
            task_management_workflow_module.workflow,
            "get_external_workflow_handle",
            Mock(return_value=handle),
        )
        monkeypatch.setattr(task_management_workflow_module.workflow, "uuid4", lambda: "ack-x")

        await workflow._signal_child_followup(message="m", artifact_ids=[], source="user")

        assert "ack-x" in workflow._pending_ack_slots
        slot = workflow._pending_ack_slots["ack-x"]
        assert slot.signal_name == "send_followup_message"
        assert slot.signal_args == ["ack-x", "m", [], "user"]
        assert slot.retry_count == 0


class TestSignalChildComplete:
    async def test_skips_when_no_sandbox_id(self, monkeypatch):
        workflow = TaskManagementWorkflow()
        workflow._run_id = "run-id"
        get_handle = Mock()
        monkeypatch.setattr(task_management_workflow_module.workflow, "get_external_workflow_handle", get_handle)

        await workflow._signal_child_complete("completed", None)

        get_handle.assert_not_called()

    async def test_signals_child_with_ack_and_slot(self, monkeypatch, fixed_now):
        workflow = TaskManagementWorkflow()
        workflow._run_id = "run-id"
        workflow._sandbox_workflow_id = "sandbox-wf"
        # Orchestrator only signals an alive sandbox now — short-circuits
        # otherwise so a dead child doesn't get spurious complete_task signals.
        workflow._sandbox_alive = True

        handle = Mock()
        handle.signal = AsyncMock()
        monkeypatch.setattr(
            task_management_workflow_module.workflow,
            "get_external_workflow_handle",
            Mock(return_value=handle),
        )
        monkeypatch.setattr(task_management_workflow_module.workflow, "uuid4", lambda: "ack-c")

        await workflow._signal_child_complete("failed", "boom")

        handle.signal.assert_awaited_once_with(
            "complete_task",
            args=["ack-c", "failed", "boom"],
        )
        slot = workflow._pending_ack_slots["ack-c"]
        assert slot.signal_name == "complete_task"
        assert slot.signal_args == ["ack-c", "failed", "boom"]


class TestNewAckId:
    def test_returns_uuid_string(self, monkeypatch):
        monkeypatch.setattr(task_management_workflow_module.workflow, "uuid4", lambda: "deterministic-id")
        workflow = TaskManagementWorkflow()
        assert workflow._new_ack_id() == "deterministic-id"


class TestRetryStaleAcks:
    """Covers the orchestrator side of "signal lost, re-forward to child".

    The child dedupes by ack_id, so the retry is safe to spam — the worst
    case is one extra round-trip. Two correctness rules:
      * Only timed-out slots get retried (others stay armed for their own
        deadlines).
      * Slots without `signal_args` (bootstrap) get dropped after timeout
        instead of retried — there's no useful "re-signal parent_attached"
        without re-executing the start activity.
    """

    async def test_resends_followup_after_ack_timeout(self, monkeypatch, fixed_now, silent_workflow_logger):
        workflow = TaskManagementWorkflow()
        workflow._run_id = "run-id"
        workflow._sandbox_workflow_id = "sandbox-wf"
        workflow._pending_ack_slots["ack-1"] = PendingAckSlot(
            signal_name="send_followup_message",
            sent_at=fixed_now.now,
            signal_args=["ack-1", "msg", [], "user"],
        )

        # Walk virtual time past ACK_TIMEOUT so the slot is considered stale.
        fixed_now.advance(ACK_TIMEOUT + timedelta(seconds=1))

        handle = Mock()
        handle.signal = AsyncMock()
        monkeypatch.setattr(
            task_management_workflow_module.workflow,
            "get_external_workflow_handle",
            Mock(return_value=handle),
        )

        await workflow._retry_stale_acks()

        handle.signal.assert_awaited_once_with(
            "send_followup_message",
            args=["ack-1", "msg", [], "user"],
        )
        slot = workflow._pending_ack_slots["ack-1"]
        assert slot.retry_count == 1
        # `sent_at` advances so we don't re-retry until the next deadline.
        assert slot.sent_at == fixed_now.now

    async def test_does_not_retry_fresh_slots(self, monkeypatch, fixed_now):
        # A slot that's only 5s old shouldn't be retried even if the retry
        # handler runs (e.g. because another slot's deadline triggered the
        # wait task).
        workflow = TaskManagementWorkflow()
        workflow._run_id = "run-id"
        workflow._sandbox_workflow_id = "sandbox-wf"
        workflow._pending_ack_slots["ack-fresh"] = PendingAckSlot(
            signal_name="send_followup_message",
            sent_at=fixed_now.now,
            signal_args=["ack-fresh", "msg", [], "user"],
        )
        fixed_now.advance(timedelta(seconds=5))

        handle = Mock()
        handle.signal = AsyncMock()
        monkeypatch.setattr(
            task_management_workflow_module.workflow,
            "get_external_workflow_handle",
            Mock(return_value=handle),
        )

        await workflow._retry_stale_acks()

        handle.signal.assert_not_awaited()
        assert workflow._pending_ack_slots["ack-fresh"].retry_count == 0

    async def test_drops_slot_after_max_retries(self, monkeypatch, fixed_now, silent_workflow_logger):
        workflow = TaskManagementWorkflow()
        workflow._run_id = "run-id"
        workflow._sandbox_workflow_id = "sandbox-wf"
        workflow._pending_ack_slots["ack-exhausted"] = PendingAckSlot(
            signal_name="send_followup_message",
            sent_at=fixed_now.now,
            signal_args=["ack-exhausted", "msg", [], "user"],
            retry_count=MAX_ACK_RETRIES,
        )
        fixed_now.advance(ACK_TIMEOUT + timedelta(seconds=1))

        handle = Mock()
        handle.signal = AsyncMock()
        monkeypatch.setattr(
            task_management_workflow_module.workflow,
            "get_external_workflow_handle",
            Mock(return_value=handle),
        )

        await workflow._retry_stale_acks()

        handle.signal.assert_not_awaited()
        assert "ack-exhausted" not in workflow._pending_ack_slots
        silent_workflow_logger.warning.assert_called()

    async def test_drops_bootstrap_slot_without_args(self, monkeypatch, fixed_now, silent_workflow_logger):
        # Bootstrap's slot doesn't carry signal_args (the actual mechanism is
        # the `ensure_execute_sandbox_started` activity, which has its own
        # retries). After timeout, just drop and log — no useful retry exists.
        workflow = TaskManagementWorkflow()
        workflow._run_id = "run-id"
        workflow._sandbox_workflow_id = "sandbox-wf"
        workflow._pending_ack_slots["bootstrap-ack"] = PendingAckSlot(
            signal_name=PARENT_ATTACHED_SIGNAL,
            sent_at=fixed_now.now,
        )
        fixed_now.advance(ACK_TIMEOUT + timedelta(seconds=1))

        handle = Mock()
        handle.signal = AsyncMock()
        monkeypatch.setattr(
            task_management_workflow_module.workflow,
            "get_external_workflow_handle",
            Mock(return_value=handle),
        )

        await workflow._retry_stale_acks()

        handle.signal.assert_not_awaited()
        assert "bootstrap-ack" not in workflow._pending_ack_slots
        silent_workflow_logger.warning.assert_called()

    async def test_retry_send_failure_keeps_slot_for_next_attempt(self, monkeypatch, fixed_now, silent_workflow_logger):
        # If the retry itself fails to deliver (child still unreachable),
        # don't advance sent_at — leave the slot so the next deadline
        # triggers another retry rather than pushing it out by ACK_TIMEOUT.
        workflow = TaskManagementWorkflow()
        workflow._run_id = "run-id"
        workflow._sandbox_workflow_id = "sandbox-wf"
        original_sent = fixed_now.now
        workflow._pending_ack_slots["ack-retry-fail"] = PendingAckSlot(
            signal_name="send_followup_message",
            sent_at=original_sent,
            signal_args=["ack-retry-fail", "msg", [], "user"],
        )
        fixed_now.advance(ACK_TIMEOUT + timedelta(seconds=1))

        handle = Mock()
        handle.signal = AsyncMock(side_effect=RuntimeError("still unreachable"))
        monkeypatch.setattr(
            task_management_workflow_module.workflow,
            "get_external_workflow_handle",
            Mock(return_value=handle),
        )

        await workflow._retry_stale_acks()

        slot = workflow._pending_ack_slots["ack-retry-fail"]
        assert slot.sent_at == original_sent
        assert slot.retry_count == 0


class TestWaitForAckRetry:
    """The wait task sleeps until the *oldest* slot's ACK deadline."""

    async def test_sleeps_until_oldest_deadline(self, monkeypatch, fixed_now):
        workflow = TaskManagementWorkflow()
        early = fixed_now.now
        late = fixed_now.now + timedelta(seconds=20)
        workflow._pending_ack_slots["a"] = PendingAckSlot(signal_name="send_followup_message", sent_at=late)
        workflow._pending_ack_slots["b"] = PendingAckSlot(signal_name="send_followup_message", sent_at=early)

        sleep_calls: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        monkeypatch.setattr(task_management_workflow_module.workflow, "sleep", fake_sleep)

        result = await workflow._wait_for_ack_retry()

        # Oldest is `early` so the deadline is early + ACK_TIMEOUT, and we
        # haven't advanced the clock — full ACK_TIMEOUT to sleep.
        assert sleep_calls == [ACK_TIMEOUT.total_seconds()]
        from products.tasks.backend.temporal.task_management.workflow import TaskEvent

        assert result is TaskEvent.ACK_RETRY_DUE

    async def test_does_not_sleep_when_deadline_already_passed(self, monkeypatch, fixed_now):
        workflow = TaskManagementWorkflow()
        workflow._pending_ack_slots["a"] = PendingAckSlot(
            signal_name="send_followup_message",
            sent_at=fixed_now.now,
        )
        fixed_now.advance(ACK_TIMEOUT * 2)

        sleep_calls: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        monkeypatch.setattr(task_management_workflow_module.workflow, "sleep", fake_sleep)

        await workflow._wait_for_ack_retry()

        assert sleep_calls == []


class TestShutdownRejectionHandling:
    """When the child rejects a follow-up because it's already shutting down,
    the orchestrator re-queues the message so it stays visible in workflow
    state for the next orchestrator execution to drain."""

    async def test_followup_rejection_requeues_to_external_queue(self, fixed_now, silent_workflow_logger):
        workflow = TaskManagementWorkflow()
        workflow._run_id = "run-id"
        workflow._pending_ack_slots["ack-shut"] = PendingAckSlot(
            signal_name="send_followup_message",
            sent_at=fixed_now.now,
            signal_args=["ack-shut", "msg-during-shutdown", ["art-1"], "user"],
        )
        workflow._child_acks.append(
            ChildAck(
                signal_name="send_followup_message",
                ack_id="ack-shut",
                accepted=False,
                detail="child_shutting_down",
                received_at=fixed_now.now,
            )
        )

        await workflow._drain_child_signals()

        # Slot is cleared (the ACK matched and was consumed) AND the
        # follow-up is back in the external queue so a future drain can
        # retry it against a fresh sandbox.
        assert "ack-shut" not in workflow._pending_ack_slots
        assert workflow._pending_external_followups == [
            PendingExternalFollowup(message="msg-during-shutdown", artifact_ids=["art-1"], source="user")
        ]
        silent_workflow_logger.warning.assert_called()

    async def test_complete_task_rejection_is_dropped_silently(self, fixed_now, silent_workflow_logger):
        # If the child rejects a `complete_task` because it's shutting down,
        # that means it's already completing — no need to re-queue anything.
        workflow = TaskManagementWorkflow()
        workflow._run_id = "run-id"
        workflow._pending_ack_slots["ack-c-shut"] = PendingAckSlot(
            signal_name="complete_task",
            sent_at=fixed_now.now,
            signal_args=["ack-c-shut", "completed", None],
        )
        workflow._child_acks.append(
            ChildAck(
                signal_name="complete_task",
                ack_id="ack-c-shut",
                accepted=False,
                detail="child_shutting_down",
                received_at=fixed_now.now,
            )
        )

        await workflow._drain_child_signals()

        assert "ack-c-shut" not in workflow._pending_ack_slots
        assert workflow._pending_external_followups == []


class TestSandboxSessionCompletionReset:
    """The orchestrator is persistent across sandbox sessions: when one ends
    we reset per-session state but stay alive for the next external signal."""

    async def test_session_completion_does_not_close_orchestrator(self, monkeypatch, fixed_now, silent_workflow_logger):
        # Hardest assertion to lose: after `_on_sandbox_session_completed`,
        # the workflow has *not* returned and is ready for more work.
        workflow = TaskManagementWorkflow()
        workflow._run_id = "run-id"
        workflow._sandbox_alive = True
        workflow._child_completion = ChildCompletion(success=True, error=None, sandbox_id="sb-1", timed_out=False)
        workflow._ci_repetitions = 2
        workflow._pr_fingerprint = "fp-1"
        workflow._heartbeat_received = True
        workflow._last_active_time = fixed_now.now
        monkeypatch.setattr(workflow, "_persist_pending_followups", AsyncMock())

        await workflow._on_sandbox_session_completed()
        workflow = workflow  # Prevent mypy from narrowing the member values and marking the code below as unreachable.
        # Per-session state has been zeroed out so the next sandbox starts clean.
        assert workflow._child_completion is None
        assert workflow._sandbox_alive is False
        assert workflow._ci_repetitions == 0
        assert workflow._pr_fingerprint is None
        assert workflow._heartbeat_received is False
        assert workflow._last_active_time is None

    async def test_unacked_followup_slots_get_requeued(self, monkeypatch, silent_workflow_logger, fixed_now):
        # If a session ends while a follow-up was awaiting ACK, the safer
        # bet is over-delivery (re-queue) rather than silent loss. The child
        # dedupes by ack_id within a session — across sessions we don't have
        # that guarantee, so a double-delivery is the cost of not losing
        # user input.
        workflow = TaskManagementWorkflow()
        workflow._run_id = "run-id"
        workflow._sandbox_alive = True
        workflow._child_completion = ChildCompletion(success=True, error=None, sandbox_id="sb-1", timed_out=False)
        workflow._pending_ack_slots["ack-pending"] = PendingAckSlot(
            signal_name="send_followup_message",
            sent_at=fixed_now.now,
            signal_args=["ack-pending", "in-flight when sandbox died", ["a1"], "user"],
        )
        # An unrelated complete_task slot should NOT be re-queued — there's
        # nothing meaningful to retry.
        workflow._pending_ack_slots["ack-complete"] = PendingAckSlot(
            signal_name="complete_task",
            sent_at=fixed_now.now,
            signal_args=["ack-complete", "completed", None],
        )
        persist_mock = AsyncMock()
        monkeypatch.setattr(workflow, "_persist_pending_followups", persist_mock)

        await workflow._on_sandbox_session_completed()

        assert workflow._pending_external_followups == [
            PendingExternalFollowup(message="in-flight when sandbox died", artifact_ids=["a1"], source="user")
        ]
        assert workflow._pending_ack_slots == {}
        persist_mock.assert_awaited()


class TestPendingFollowupPersistence:
    async def test_restore_pending_seeds_in_memory_queue(self, monkeypatch, silent_workflow_logger):
        # An orchestrator that restarts must rebuild its queue from
        # TaskRun.state so user messages that landed against the previous
        # execution aren't dropped.
        from products.tasks.backend.temporal.task_management.activities.pending_followups import (
            ReadPendingFollowupsResult,
            read_pending_followups,
        )

        workflow = TaskManagementWorkflow()
        workflow._run_id = "run-id"

        async def fake_execute_activity(activity_fn, *args, **kwargs):
            assert activity_fn is read_pending_followups
            return ReadPendingFollowupsResult(
                followups=[
                    {"message": "queued-1", "artifact_ids": [], "source": "user"},
                    {"message": "queued-2", "artifact_ids": ["a1"], "source": "user"},
                ]
            )

        monkeypatch.setattr(task_management_workflow_module.workflow, "execute_activity", fake_execute_activity)

        await workflow._restore_pending_followups()

        assert workflow._pending_external_followups == [
            PendingExternalFollowup(message="queued-1", artifact_ids=[], source="user"),
            PendingExternalFollowup(message="queued-2", artifact_ids=["a1"], source="user"),
        ]

    async def test_restore_swallows_read_error(self, monkeypatch, silent_workflow_logger):
        workflow = TaskManagementWorkflow()
        workflow._run_id = "run-id"

        async def boom(*args, **kwargs):
            raise RuntimeError("db down")

        monkeypatch.setattr(task_management_workflow_module.workflow, "execute_activity", boom)

        await workflow._restore_pending_followups()

        assert workflow._pending_external_followups == []
        silent_workflow_logger.warning.assert_called()

    async def test_persist_writes_current_queue(self, monkeypatch):
        from products.tasks.backend.temporal.task_management.activities.pending_followups import (
            persist_pending_followups,
        )

        workflow = TaskManagementWorkflow()
        workflow._run_id = "run-id"
        workflow._pending_external_followups.append(
            PendingExternalFollowup(message="persist-me", artifact_ids=["a1"], source="user")
        )

        captured: dict = {}

        async def fake_execute_activity(activity_fn, input_arg, *args, **kwargs):
            assert activity_fn is persist_pending_followups
            captured["input"] = input_arg
            return None

        monkeypatch.setattr(task_management_workflow_module.workflow, "execute_activity", fake_execute_activity)

        await workflow._persist_pending_followups()

        assert captured["input"].run_id == "run-id"
        assert captured["input"].followups == [{"message": "persist-me", "artifact_ids": ["a1"], "source": "user"}]
