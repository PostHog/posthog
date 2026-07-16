import asyncio

import pytest
from unittest.mock import AsyncMock, Mock

from temporalio.exceptions import ActivityError, RetryState

from products.tasks.backend.temporal.execute_sandbox import workflow as execute_sandbox_workflow_module
from products.tasks.backend.temporal.execute_sandbox.activities.reap_orphaned_sandbox import (
    ReapOrphanedSandboxInput,
    ReapOrphanedSandboxResult,
    reap_orphaned_sandbox,
)
from products.tasks.backend.temporal.execute_sandbox.workflow import (
    PARENT_ACK_SIGNAL,
    PARENT_ATTACHED_SIGNAL,
    PARENT_COMPLETED_SIGNAL,
    PARENT_HEARTBEAT_SIGNAL,
    ChildCompletionPayload,
    ExecuteSandboxInput,
    ExecuteSandboxWorkflow,
    OutboundSignal,
    PendingFollowup,
    SandboxEvent,
)
from products.tasks.backend.temporal.process_task.activities.get_sandbox_for_repository import (
    GetSandboxForRepositoryOutput,
)
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.start_agent_server import StartAgentServerOutput
from products.tasks.backend.temporal.process_task.credential_refresh import CredentialRefreshExitReason


def _build_context(
    *,
    github_integration_id: int | None = 123,
    repository: str | None = "posthog/posthog-js",
    state: dict | None = None,
    use_modal_resume_snapshots: bool = True,
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
        use_modal_resume_snapshots=use_modal_resume_snapshots,
    )


@pytest.fixture
def silent_workflow_logger(monkeypatch):
    """Replace `workflow.logger` with a Mock so handlers can log outside a workflow context."""
    logger = Mock()
    monkeypatch.setattr(execute_sandbox_workflow_module.workflow, "logger", logger)
    return logger


class TestActivityErrorProperties:
    def test_returns_full_context_for_activity_error(self):
        # Mirrors process_task — the new workflow keeps the same surface for
        # PostHog event capture so dashboards continue to slice by these props.
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

        assert ExecuteSandboxWorkflow._activity_error_properties(error) == {
            "temporal_activity_id": "activity-1",
            "temporal_activity_type": "get_pr_context",
            "temporal_activity_identity": "worker-1",
            "temporal_activity_retry_state": "TIMEOUT",
            "temporal_activity_scheduled_event_id": 10,
            "temporal_activity_started_event_id": 11,
            "cause_error_type": "TimeoutError",
            "cause_error_message": "start-to-close timeout",
        }

    def test_returns_empty_dict_for_non_activity_error(self):
        assert ExecuteSandboxWorkflow._activity_error_properties(RuntimeError("boom")) == {}


class TestShouldSkipFollowup:
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
    def test_skips_only_when_message_and_artifacts_both_empty(
        self, message: str | None, artifact_ids: list[str], expected: bool
    ):
        assert ExecuteSandboxWorkflow._should_skip_followup(message, artifact_ids) is expected


class TestShouldForwardPendingUserMessage:
    @pytest.mark.parametrize(
        "state,expected",
        [
            # Interactive mode is the only path that surfaces the pending
            # message directly via the UI — no need for the workflow to forward.
            ({"mode": "interactive", "pending_user_message": "hi"}, False),
            # Background mode is the normal "queue and forward" path.
            ({"mode": "background", "pending_user_message": "hi"}, True),
            # Resume runs already replay the original prompt — forwarding would
            # double up. Both resume markers must short-circuit.
            ({"mode": "background", "resume_from_run_id": "prev"}, False),
            ({"mode": "background", "handoff_resumed": True}, False),
        ],
    )
    def test_forwards_only_in_background_and_not_on_resume(self, state: dict, expected: bool):
        workflow = ExecuteSandboxWorkflow()
        workflow._context = _build_context(state=state)
        assert workflow._should_forward_pending_user_message() is expected

    def test_returns_false_when_context_is_unset(self):
        # Signal handlers can fire before the context is loaded; the guard
        # must keep us from raising on a missing context.
        workflow = ExecuteSandboxWorkflow()
        assert workflow._should_forward_pending_user_message() is False


class TestParseInputs:
    def test_parses_required_and_optional_fields(self):
        raw = (
            '{"run_id":"r","parent_workflow_id":"p","create_pr":false,'
            '"slack_thread_context":{"channel":"C1"},"posthog_mcp_scopes":"full"}'
        )
        parsed = ExecuteSandboxWorkflow.parse_inputs([raw])
        assert parsed == ExecuteSandboxInput(
            run_id="r",
            parent_workflow_id="p",
            create_pr=False,
            slack_thread_context={"channel": "C1"},
            posthog_mcp_scopes="full",
        )

    def test_applies_defaults_for_missing_optional_fields(self):
        parsed = ExecuteSandboxWorkflow.parse_inputs(['{"run_id":"r","parent_workflow_id":"p"}'])
        assert parsed.create_pr is True
        assert parsed.slack_thread_context is None
        assert parsed.posthog_mcp_scopes == "read_only"


class TestSignalHandlers:
    async def test_parent_attached_sets_parent_id_and_queues_ack(self, silent_workflow_logger):
        workflow = ExecuteSandboxWorkflow()

        await workflow.parent_attached("ack-1", "parent-wf-id")

        assert workflow._parent_workflow_id == "parent-wf-id"
        assert workflow._pending_outbound == [
            OutboundSignal(
                target_signal=PARENT_ACK_SIGNAL,
                args=[PARENT_ATTACHED_SIGNAL, "ack-1", True, None],
                correlation_id="ack-1",
            )
        ]

    async def test_complete_task_sets_completion_state_and_queues_ack(self, silent_workflow_logger):
        workflow = ExecuteSandboxWorkflow()

        await workflow.complete_task("ack-2", status="failed", error_message="boom")

        assert workflow._task_completed is True
        assert workflow._completion_status == "failed"
        assert workflow._completion_error == "boom"
        assert workflow._pending_outbound == [
            OutboundSignal(
                target_signal=PARENT_ACK_SIGNAL,
                args=["complete_task", "ack-2", True, None],
                correlation_id="ack-2",
            )
        ]

    async def test_send_followup_message_queues_pending_followup_without_ack(self, silent_workflow_logger):
        # ACK is deferred until the main loop actually dispatches — the
        # handler only enqueues. Logging is the only visible side-effect here.
        workflow = ExecuteSandboxWorkflow()
        workflow._context = _build_context()

        await workflow.send_followup_message("ack-3", "hello", ["art-1"], source="user")

        assert workflow._pending_followups == [
            PendingFollowup(message="hello", artifact_ids=["art-1"], ack_id="ack-3", source="user")
        ]
        assert workflow._pending_outbound == []
        silent_workflow_logger.info.assert_called()

    async def test_send_followup_message_handles_missing_optional_fields(self, silent_workflow_logger):
        workflow = ExecuteSandboxWorkflow()

        await workflow.send_followup_message("ack-3")

        assert workflow._pending_followups == [
            PendingFollowup(message=None, artifact_ids=[], ack_id="ack-3", source="user")
        ]

    async def test_heartbeat_from_relay_sets_flag_and_forwards(self, silent_workflow_logger):
        # Heartbeats only ever flow child -> parent. The in-workflow relay
        # signals us; we record activity locally and forward to the parent
        # to drive its CI follow-up timing.
        workflow = ExecuteSandboxWorkflow()

        await workflow.heartbeat(agent_active=True)

        assert workflow._heartbeat_received is True
        assert workflow._pending_outbound == [OutboundSignal(target_signal=PARENT_HEARTBEAT_SIGNAL, args=[True])]


class TestEnqueueHelpers:
    def test_enqueue_ack_defaults_to_accepted_true_and_no_detail(self):
        workflow = ExecuteSandboxWorkflow()
        workflow._enqueue_ack(signal_name="send_followup_message", ack_id="x")

        assert workflow._pending_outbound == [
            OutboundSignal(
                target_signal=PARENT_ACK_SIGNAL,
                args=["send_followup_message", "x", True, None],
                correlation_id="x",
            )
        ]

    def test_enqueue_ack_propagates_rejection_and_detail(self):
        workflow = ExecuteSandboxWorkflow()
        workflow._enqueue_ack(
            signal_name="send_followup_message",
            ack_id="y",
            accepted=False,
            detail="empty follow-up skipped",
        )

        assert workflow._pending_outbound[0].args == [
            "send_followup_message",
            "y",
            False,
            "empty follow-up skipped",
        ]

    def test_enqueue_completed_signal_uses_terminal_target(self):
        # Wire format is a single dataclass arg so the four fields can grow
        # without touching call sites on either side of the signal.
        workflow = ExecuteSandboxWorkflow()
        payload = ChildCompletionPayload(success=True, error=None, sandbox_id="sb-1", timed_out=False)
        workflow._enqueue_completed_signal(payload)

        assert workflow._pending_outbound == [
            OutboundSignal(
                target_signal=PARENT_COMPLETED_SIGNAL,
                args=[payload],
            )
        ]


class TestFlushPendingOutbound:
    async def test_no_op_when_no_parent_workflow_id_yet(self):
        # The bootstrap signal might land slightly after a relay heartbeat in
        # rare races. Without a parent id we can't deliver, so we silently
        # skip and try again on the next flush.
        workflow = ExecuteSandboxWorkflow()
        workflow._pending_outbound.append(OutboundSignal(target_signal=PARENT_HEARTBEAT_SIGNAL, args=[True]))

        await workflow._flush_pending_outbound()

        # Outbound preserved for a later flush.
        assert len(workflow._pending_outbound) == 1

    async def test_drains_outbound_through_external_handle(self, monkeypatch):
        workflow = ExecuteSandboxWorkflow()
        workflow._parent_workflow_id = "parent-wf"
        workflow._pending_outbound.extend(
            [
                OutboundSignal(target_signal=PARENT_ACK_SIGNAL, args=["complete_task", "a1", True, None]),
                OutboundSignal(target_signal=PARENT_HEARTBEAT_SIGNAL, args=[False]),
            ]
        )

        signal_mock = AsyncMock()
        handle_mock = Mock()
        handle_mock.signal = signal_mock
        get_handle_mock = Mock(return_value=handle_mock)
        monkeypatch.setattr(
            execute_sandbox_workflow_module.workflow,
            "get_external_workflow_handle",
            get_handle_mock,
        )

        await workflow._flush_pending_outbound()

        assert workflow._pending_outbound == []
        get_handle_mock.assert_called_once_with("parent-wf")
        assert signal_mock.await_count == 2
        assert signal_mock.await_args_list[0].args[0] == PARENT_ACK_SIGNAL
        assert signal_mock.await_args_list[1].args[0] == PARENT_HEARTBEAT_SIGNAL

    async def test_requeues_failed_outbound_for_next_flush(self, monkeypatch, silent_workflow_logger):
        # If the parent handle is momentarily unreachable, the signal stays
        # in the outbound queue — the loop will try again on the next event.
        workflow = ExecuteSandboxWorkflow()
        workflow._context = _build_context()
        workflow._parent_workflow_id = "parent-wf"
        original = OutboundSignal(target_signal=PARENT_ACK_SIGNAL, args=["complete_task", "a1", True, None])
        workflow._pending_outbound.append(original)

        signal_mock = AsyncMock(side_effect=RuntimeError("parent unreachable"))
        handle_mock = Mock()
        handle_mock.signal = signal_mock
        monkeypatch.setattr(
            execute_sandbox_workflow_module.workflow,
            "get_external_workflow_handle",
            Mock(return_value=handle_mock),
        )
        sleep_mock = AsyncMock()
        monkeypatch.setattr(execute_sandbox_workflow_module.workflow, "sleep", sleep_mock)

        await workflow._flush_pending_outbound()

        assert workflow._pending_outbound == [original]
        silent_workflow_logger.warning.assert_called()
        # Backoff rate-limits the next retry — without this sleep the main
        # loop's wait condition (`len(_pending_outbound) > 0`) would fire
        # immediately and tight-loop against the unreachable parent.
        sleep_mock.assert_awaited_once()

    async def test_no_backoff_when_flush_succeeds(self, monkeypatch):
        workflow = ExecuteSandboxWorkflow()
        workflow._context = _build_context()
        workflow._parent_workflow_id = "parent-wf"
        workflow._pending_outbound.append(
            OutboundSignal(target_signal=PARENT_ACK_SIGNAL, args=["complete_task", "a1", True, None])
        )

        handle_mock = Mock()
        handle_mock.signal = AsyncMock()
        monkeypatch.setattr(
            execute_sandbox_workflow_module.workflow,
            "get_external_workflow_handle",
            Mock(return_value=handle_mock),
        )
        sleep_mock = AsyncMock()
        monkeypatch.setattr(execute_sandbox_workflow_module.workflow, "sleep", sleep_mock)

        await workflow._flush_pending_outbound()

        # All sent successfully — no rate-limit needed on the happy path.
        sleep_mock.assert_not_awaited()


class TestHandleFollowup:
    async def test_empty_followup_is_skipped_and_acked_as_rejected(self, monkeypatch, silent_workflow_logger):
        workflow = ExecuteSandboxWorkflow()
        workflow._context = _build_context()
        workflow._parent_workflow_id = "parent-wf"

        send_mock = AsyncMock()
        monkeypatch.setattr(workflow, "_send_followup_to_sandbox", send_mock)
        flush_mock = AsyncMock()
        monkeypatch.setattr(workflow, "_flush_pending_outbound", flush_mock)

        await workflow._handle_followup(PendingFollowup(message=None, artifact_ids=[], ack_id="ack-e"))

        send_mock.assert_not_awaited()
        # Empty follow-ups still need an ACK so the parent stops waiting.
        assert workflow._pending_outbound == [
            OutboundSignal(
                target_signal=PARENT_ACK_SIGNAL,
                args=["send_followup_message", "ack-e", False, "empty follow-up skipped"],
                correlation_id="ack-e",
            )
        ]
        flush_mock.assert_awaited()

    async def test_success_dispatches_and_acks_accepted(self, monkeypatch):
        workflow = ExecuteSandboxWorkflow()
        workflow._context = _build_context()
        workflow._parent_workflow_id = "parent-wf"

        send_mock = AsyncMock()
        monkeypatch.setattr(workflow, "_send_followup_to_sandbox", send_mock)
        monkeypatch.setattr(workflow, "_flush_pending_outbound", AsyncMock())

        await workflow._handle_followup(
            PendingFollowup(message="msg", artifact_ids=["art-1"], ack_id="ack-ok", source="user")
        )

        send_mock.assert_awaited_once_with(message="msg", artifact_ids=["art-1"])
        assert workflow._pending_outbound == [
            OutboundSignal(
                target_signal=PARENT_ACK_SIGNAL,
                args=["send_followup_message", "ack-ok", True, None],
                correlation_id="ack-ok",
            )
        ]
        # A successful follow-up must not look like a completion.
        assert workflow._task_completed is False

    async def test_dispatch_failure_marks_task_failed_and_acks_failure(self, monkeypatch, silent_workflow_logger):
        # Mirrors process_task behaviour — a failed dispatch is terminal and
        # must surface through both the ACK (so the orchestrator knows the
        # follow-up was rejected) and the task-completion path.
        workflow = ExecuteSandboxWorkflow()
        workflow._context = _build_context()
        workflow._parent_workflow_id = "parent-wf"

        send_mock = AsyncMock(side_effect=RuntimeError("sandbox is dead"))
        monkeypatch.setattr(workflow, "_send_followup_to_sandbox", send_mock)
        monkeypatch.setattr(workflow, "_flush_pending_outbound", AsyncMock())

        await workflow._handle_followup(PendingFollowup(message="msg", artifact_ids=[], ack_id="ack-fail"))

        assert workflow._task_completed is True
        assert workflow._completion_status == "failed"
        assert workflow._completion_error == "Follow-up delivery failed: sandbox is dead"
        assert workflow._completion_error_type == "followup_delivery_failed"
        ack = workflow._pending_outbound[-1]
        assert ack.target_signal == PARENT_ACK_SIGNAL
        assert ack.args[0] == "send_followup_message"
        assert ack.args[1] == "ack-fail"
        assert ack.args[2] is False
        assert "sandbox is dead" in (ack.args[3] or "")

    async def test_dispatch_failure_unwraps_activity_error_cause(self, monkeypatch, silent_workflow_logger):
        workflow = ExecuteSandboxWorkflow()
        workflow._context = _build_context()
        workflow._parent_workflow_id = "parent-wf"

        activity_error = ActivityError(
            "Activity task failed",
            scheduled_event_id=1,
            started_event_id=2,
            identity="worker-1",
            activity_type="send_followup_to_sandbox",
            activity_id="activity-1",
            retry_state=RetryState.MAXIMUM_ATTEMPTS_REACHED,
        )
        activity_error.__cause__ = RuntimeError("send_followup failed: sandbox unreachable")

        send_mock = AsyncMock(side_effect=activity_error)
        monkeypatch.setattr(workflow, "_send_followup_to_sandbox", send_mock)
        monkeypatch.setattr(workflow, "_flush_pending_outbound", AsyncMock())

        await workflow._handle_followup(PendingFollowup(message="msg", artifact_ids=[], ack_id="ack-fail"))

        assert workflow._task_completed is True
        assert workflow._completion_status == "failed"
        assert workflow._completion_error == "Follow-up delivery failed: send_followup failed: sandbox unreachable"
        assert workflow._completion_error_type == "followup_delivery_failed"
        ack = workflow._pending_outbound[-1]
        assert ack.args[3] == "send_followup failed: sandbox unreachable"


class TestReapOrphanedSandbox:
    """The reaper is one activity now: read + Modal destroy + clear-state all
    happen inside `reap_orphaned_sandbox`. The workflow's only job is to call
    it and log the outcome."""

    async def test_no_op_when_no_persisted_id(self, monkeypatch):
        workflow = ExecuteSandboxWorkflow()
        calls: list[tuple[object, object]] = []

        async def fake_execute_activity(activity_fn, input_arg, *args, **kwargs):
            calls.append((activity_fn, input_arg))
            if activity_fn is reap_orphaned_sandbox:
                assert isinstance(input_arg, ReapOrphanedSandboxInput)
                return ReapOrphanedSandboxResult(reaped_sandbox_id=None, destroy_succeeded=True)
            raise AssertionError(f"unexpected activity call: {activity_fn}")

        monkeypatch.setattr(execute_sandbox_workflow_module.workflow, "execute_activity", fake_execute_activity)

        await workflow._reap_orphaned_sandbox("run-1")

        # Single round-trip — the workflow no longer needs read/cleanup/clear
        # as three separate calls.
        assert [fn for fn, _ in calls] == [reap_orphaned_sandbox]

    async def test_logs_reaped_id_when_orphan_present(self, monkeypatch, silent_workflow_logger):
        workflow = ExecuteSandboxWorkflow()

        async def fake_execute_activity(activity_fn, input_arg, *args, **kwargs):
            assert activity_fn is reap_orphaned_sandbox
            return ReapOrphanedSandboxResult(reaped_sandbox_id="sb-orphan", destroy_succeeded=True)

        monkeypatch.setattr(execute_sandbox_workflow_module.workflow, "execute_activity", fake_execute_activity)

        await workflow._reap_orphaned_sandbox("run-1")

        # Observable side-effect from the workflow's side is the log line —
        # the actual destroy + state-clear happened inside the activity.
        silent_workflow_logger.info.assert_called()

    async def test_swallows_activity_error_and_returns(self, monkeypatch, silent_workflow_logger):
        # If the consolidated activity itself fails, log and move on — the
        # Modal-side per-sandbox TTL is the final safety net and the next
        # workflow start will retry the reap.
        workflow = ExecuteSandboxWorkflow()

        async def fake_execute_activity(activity_fn, *args, **kwargs):
            raise RuntimeError("db unreachable")

        monkeypatch.setattr(execute_sandbox_workflow_module.workflow, "execute_activity", fake_execute_activity)

        await workflow._reap_orphaned_sandbox("run-1")

        silent_workflow_logger.warning.assert_called()

    async def test_logs_destroy_outcome_when_modal_call_fails(self, monkeypatch, silent_workflow_logger):
        # When the activity destroyed-or-tried-to-destroy and cleared state
        # but Modal returned an error, the workflow still treats this as
        # a successful reap (state is clear) — destroy_succeeded=False just
        # surfaces in the log so operators can see it.
        workflow = ExecuteSandboxWorkflow()

        async def fake_execute_activity(activity_fn, *args, **kwargs):
            assert activity_fn is reap_orphaned_sandbox
            return ReapOrphanedSandboxResult(reaped_sandbox_id="sb-orphan", destroy_succeeded=False)

        monkeypatch.setattr(execute_sandbox_workflow_module.workflow, "execute_activity", fake_execute_activity)

        await workflow._reap_orphaned_sandbox("run-1")

        silent_workflow_logger.info.assert_called()


class TestPersistSandboxId:
    async def test_swallows_persist_error(self, monkeypatch, silent_workflow_logger):
        # Persist failures must not abort the run — the Modal TTL is the
        # final backstop if cleanup is later missed.
        workflow = ExecuteSandboxWorkflow()

        async def boom(*args, **kwargs):
            raise RuntimeError("db hiccup")

        monkeypatch.setattr(execute_sandbox_workflow_module.workflow, "execute_activity", boom)

        await workflow._persist_sandbox_id("run-1", "sb-1")

        silent_workflow_logger.warning.assert_called()


class TestRun:
    async def test_credential_refresh_exit_marks_sandbox_gone(self, monkeypatch, silent_workflow_logger):
        workflow = ExecuteSandboxWorkflow()
        workflow._context = _build_context()
        refresh_loop_mock = AsyncMock(return_value=CredentialRefreshExitReason.SANDBOX_GONE)

        monkeypatch.setattr(execute_sandbox_workflow_module, "run_credential_refresh_loop", refresh_loop_mock)

        await workflow._run_credential_refresh_until_sandbox_gone("sandbox-123")

        assert workflow._sandbox_gone is True
        refresh_loop_mock.assert_awaited_once_with(workflow.context, "sandbox-123")
        silent_workflow_logger.warning.assert_called_once_with(
            "execute_sandbox_sandbox_gone_detected",
            run_id="run-id",
            sandbox_id="sandbox-123",
        )

    async def test_credential_refresh_credentials_unavailable_does_not_mark_sandbox_gone(
        self, monkeypatch, silent_workflow_logger
    ):
        workflow = ExecuteSandboxWorkflow()
        workflow._context = _build_context()
        refresh_loop_mock = AsyncMock(return_value=CredentialRefreshExitReason.CREDENTIALS_UNAVAILABLE)

        monkeypatch.setattr(execute_sandbox_workflow_module, "run_credential_refresh_loop", refresh_loop_mock)

        await workflow._run_credential_refresh_until_sandbox_gone("sandbox-123")

        assert workflow._sandbox_gone is False
        silent_workflow_logger.warning.assert_called_once_with(
            "execute_sandbox_credential_refresh_stopped_credentials_unavailable",
            run_id="run-id",
            sandbox_id="sandbox-123",
        )

    @pytest.mark.parametrize(
        "use_modal_resume_snapshots, expect_resume_snapshot_call",
        [
            (True, True),
            (False, False),
        ],
    )
    async def test_run_ends_session_without_failing_when_sandbox_gone(
        self, monkeypatch, silent_workflow_logger, use_modal_resume_snapshots, expect_resume_snapshot_call
    ):
        workflow = ExecuteSandboxWorkflow()
        context = _build_context(
            state={"mode": "interactive"},
            use_modal_resume_snapshots=use_modal_resume_snapshots,
        )
        update_status_mock = AsyncMock()
        cleanup_sandbox_mock = AsyncMock()
        create_resume_snapshot_mock = AsyncMock()

        monkeypatch.setattr(workflow, "_reap_orphaned_sandbox", AsyncMock())
        monkeypatch.setattr(workflow, "_get_task_processing_context", AsyncMock(return_value=context))
        monkeypatch.setattr(workflow, "_update_task_run_status", update_status_mock)
        monkeypatch.setattr(workflow, "_emit_progress", AsyncMock())
        monkeypatch.setattr(workflow, "_track_workflow_event", AsyncMock())
        monkeypatch.setattr(workflow, "_persist_sandbox_id", AsyncMock())
        monkeypatch.setattr(workflow, "_read_sandbox_logs", AsyncMock())
        monkeypatch.setattr(workflow, "_cleanup_sandbox", cleanup_sandbox_mock)
        monkeypatch.setattr(workflow, "_create_resume_snapshot", create_resume_snapshot_mock)
        monkeypatch.setattr(workflow, "_clear_persisted_sandbox_id", AsyncMock())
        monkeypatch.setattr(workflow, "_flush_pending_outbound", AsyncMock())
        monkeypatch.setattr(workflow, "_relay_sandbox_events", AsyncMock())
        monkeypatch.setattr(workflow, "_run_credential_refresh_until_sandbox_gone", AsyncMock())
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
        monkeypatch.setattr(workflow, "_wait_for_event", AsyncMock(return_value=SandboxEvent.SANDBOX_GONE))

        result = await workflow.run(ExecuteSandboxInput(run_id="run-id", parent_workflow_id="parent-wf-id"))

        assert result.success is True
        assert workflow._completion_status == "completed"
        terminal_status_writes = [
            call for call in update_status_mock.await_args_list if call.args[:1] in (("failed",), ("cancelled",))
        ]
        assert terminal_status_writes == []
        cleanup_sandbox_mock.assert_awaited_once_with("sandbox-123")
        completed_signals = [
            outbound for outbound in workflow._pending_outbound if outbound.target_signal == PARENT_COMPLETED_SIGNAL
        ]
        assert len(completed_signals) == 1
        payload = completed_signals[0].args[0]
        assert isinstance(payload, ChildCompletionPayload)
        assert payload.success is True
        if expect_resume_snapshot_call:
            create_resume_snapshot_mock.assert_awaited_once_with("sandbox-123")
        else:
            create_resume_snapshot_mock.assert_not_awaited()

    async def test_context_load_failure_marks_run_failed(self, monkeypatch, silent_workflow_logger):
        workflow = ExecuteSandboxWorkflow()
        get_context_mock = AsyncMock(side_effect=RuntimeError("database connection closed"))
        update_status_mock = AsyncMock()
        track_event_mock = AsyncMock()
        reap_mock = AsyncMock()

        monkeypatch.setattr(workflow, "_get_task_processing_context", get_context_mock)
        monkeypatch.setattr(workflow, "_update_task_run_status", update_status_mock)
        monkeypatch.setattr(workflow, "_track_workflow_event", track_event_mock)
        monkeypatch.setattr(workflow, "_reap_orphaned_sandbox", reap_mock)
        monkeypatch.setattr(workflow, "_flush_pending_outbound", AsyncMock())

        result = await workflow.run(ExecuteSandboxInput(run_id="run-id", parent_workflow_id="parent-wf-id"))

        assert result.success is False
        assert result.error == "database connection closed"
        assert result.sandbox_id is None
        assert result.timed_out is False
        update_status_mock.assert_awaited_with(
            "failed",
            error_message="database connection closed",
            run_id="run-id",
            error_type="RuntimeError",
        )
        # A terminal completion signal is enqueued even on failure paths so
        # the orchestrator never waits indefinitely on a silent child.
        reap_mock.assert_awaited_once_with("run-id")


class TestAckDedupe:
    """Inbound signal handlers must dedupe on `ack_id` so the orchestrator's
    retry path (resend same ack_id when ACK is lost) doesn't double-process."""

    async def test_complete_task_replay_only_re_acks(self, silent_workflow_logger):
        workflow = ExecuteSandboxWorkflow()
        # Simulate the original send/process having already happened: the
        # ack_id is in _acked_ids and the completion state is set.
        workflow._acked_ids.add("ack-c")
        workflow._completion_status = "completed"
        workflow._task_completed = True
        # Clear outbound so we can see only the re-ack below.
        workflow._pending_outbound.clear()

        await workflow.complete_task("ack-c", status="failed", error_message="late retry")

        # State unchanged — the retry's "failed" payload must not overwrite
        # the original completion that we already acknowledged.
        assert workflow._completion_status == "completed"
        assert workflow._completion_error is None
        # Single re-ack queued, no re-application of the new status.
        assert workflow._pending_outbound == [
            OutboundSignal(
                target_signal=PARENT_ACK_SIGNAL,
                args=["complete_task", "ack-c", True, None],
                correlation_id="ack-c",
            )
        ]

    async def test_send_followup_replay_does_not_double_queue(self, silent_workflow_logger):
        # If the message has already been processed (ack_id in _acked_ids),
        # the retry just re-acks. No new PendingFollowup is queued.
        workflow = ExecuteSandboxWorkflow()
        workflow._context = _build_context()
        workflow._acked_ids.add("ack-f")
        workflow._pending_outbound.clear()

        await workflow.send_followup_message("ack-f", "msg", ["a1"])

        assert workflow._pending_followups == []
        assert workflow._pending_outbound == [
            OutboundSignal(
                target_signal=PARENT_ACK_SIGNAL,
                args=["send_followup_message", "ack-f", True, None],
                correlation_id="ack-f",
            )
        ]

    async def test_send_followup_inflight_retry_is_dropped_quietly(self, silent_workflow_logger):
        # Retry arrives while the original PendingFollowup is still in the
        # queue (not yet dispatched). Drop the duplicate — the original will
        # ack when it dispatches.
        workflow = ExecuteSandboxWorkflow()
        workflow._context = _build_context()
        workflow._pending_followups.append(PendingFollowup(message="msg", artifact_ids=[], ack_id="ack-inflight"))
        workflow._pending_outbound.clear()

        await workflow.send_followup_message("ack-inflight", "msg")

        # Pending queue unchanged — no duplicate appended.
        assert len(workflow._pending_followups) == 1
        # No premature ack — the original ack will go out at dispatch time.
        assert workflow._pending_outbound == []

    async def test_send_followup_mid_dispatch_retry_is_dropped_quietly(self, silent_workflow_logger):
        # The risky case: original was popped from pending and is mid-dispatch
        # (awaiting `_send_followup_to_sandbox`). A retry arriving here must
        # not re-queue or re-ack — the original's ACK is the source of truth.
        workflow = ExecuteSandboxWorkflow()
        workflow._context = _build_context()
        workflow._in_flight_followup_ack_ids.add("ack-mid")
        workflow._pending_outbound.clear()

        await workflow.send_followup_message("ack-mid", "msg")

        assert workflow._pending_followups == []
        assert workflow._pending_outbound == []


class TestHandleFollowupInFlightTracking:
    async def test_in_flight_set_populated_before_first_await(self, monkeypatch, silent_workflow_logger):
        # Capture the in-flight set state at the moment _send_followup_to_sandbox
        # is entered — must already contain our ack_id. This is the property
        # that lets a retry-arriving-mid-dispatch dedupe correctly.
        workflow = ExecuteSandboxWorkflow()
        workflow._context = _build_context()

        snapshot: dict[str, bool] = {}

        async def fake_send(message=None, artifact_ids=None):
            snapshot["in_flight_at_await"] = "ack-track" in workflow._in_flight_followup_ack_ids

        monkeypatch.setattr(workflow, "_send_followup_to_sandbox", fake_send)
        monkeypatch.setattr(workflow, "_flush_pending_outbound", AsyncMock())

        await workflow._handle_followup(PendingFollowup(message="msg", artifact_ids=[], ack_id="ack-track"))

        assert snapshot["in_flight_at_await"] is True
        # And it must be cleared again once dispatch finishes.
        assert "ack-track" not in workflow._in_flight_followup_ack_ids
        # ACK still went out.
        assert "ack-track" in workflow._acked_ids

    async def test_in_flight_cleared_even_on_dispatch_failure(self, monkeypatch, silent_workflow_logger):
        workflow = ExecuteSandboxWorkflow()
        workflow._context = _build_context()

        async def fake_send_raises(message=None, artifact_ids=None):
            raise RuntimeError("sandbox dead")

        monkeypatch.setattr(workflow, "_send_followup_to_sandbox", fake_send_raises)
        monkeypatch.setattr(workflow, "_flush_pending_outbound", AsyncMock())

        await workflow._handle_followup(PendingFollowup(message="msg", artifact_ids=[], ack_id="ack-fail"))

        assert "ack-fail" not in workflow._in_flight_followup_ack_ids
        assert "ack-fail" in workflow._acked_ids

    async def test_parent_attached_replay_only_re_acks(self, silent_workflow_logger):
        workflow = ExecuteSandboxWorkflow()
        workflow._parent_workflow_id = "original-parent"
        workflow._acked_ids.add("ack-attach")
        workflow._pending_outbound.clear()

        await workflow.parent_attached("ack-attach", "new-parent")

        # parent_workflow_id should not be overwritten on replay.
        assert workflow._parent_workflow_id == "original-parent"
        assert workflow._pending_outbound == [
            OutboundSignal(
                target_signal=PARENT_ACK_SIGNAL,
                args=[PARENT_ATTACHED_SIGNAL, "ack-attach", True, None],
                correlation_id="ack-attach",
            )
        ]

    def test_enqueue_ack_records_ack_id(self):
        # Sanity check: the dedupe set is populated as a side-effect of acking.
        # If this regresses, all the dedupe paths above would silently break.
        workflow = ExecuteSandboxWorkflow()
        workflow._enqueue_ack(signal_name="complete_task", ack_id="x")
        assert "x" in workflow._acked_ids


class TestShutdownRejection:
    """During the cleanup window (`_shutting_down=True`), signals that would
    normally queue new work are rejected so the orchestrator's retry path
    can route them to a fresh sandbox instead of silently losing them."""

    async def test_send_followup_rejected_with_known_detail(self, silent_workflow_logger):
        workflow = ExecuteSandboxWorkflow()
        workflow._context = _build_context()
        workflow._shutting_down = True
        workflow._pending_outbound.clear()

        await workflow.send_followup_message("ack-late", "post-shutdown msg")

        # No queueing — the message goes nowhere on the sandbox side.
        assert workflow._pending_followups == []
        # The orchestrator's `_drain_child_signals` keys off detail="child_shutting_down"
        # exactly — don't change this string without updating both sides.
        assert workflow._pending_outbound == [
            OutboundSignal(
                target_signal=PARENT_ACK_SIGNAL,
                args=["send_followup_message", "ack-late", False, "child_shutting_down"],
                correlation_id="ack-late",
            )
        ]

    async def test_complete_task_rejected_with_known_detail(self, silent_workflow_logger):
        workflow = ExecuteSandboxWorkflow()
        workflow._shutting_down = True
        workflow._pending_outbound.clear()

        await workflow.complete_task("ack-late-c", status="failed", error_message="boom")

        # State unchanged — we're already winding down with our own completion
        # status; a late external complete must not overwrite it.
        assert workflow._completion_status == "completed"
        assert workflow._pending_outbound == [
            OutboundSignal(
                target_signal=PARENT_ACK_SIGNAL,
                args=["complete_task", "ack-late-c", False, "child_shutting_down"],
                correlation_id="ack-late-c",
            )
        ]

    async def test_dedupe_check_wins_over_shutdown_check(self, silent_workflow_logger):
        # If a signal arrives during shutdown but was ALREADY processed
        # before shutdown began, treat it as a successful retry — re-ack with
        # accepted=True rather than rejecting. Otherwise the orchestrator
        # might think a successfully-delivered follow-up was lost.
        workflow = ExecuteSandboxWorkflow()
        workflow._context = _build_context()
        workflow._shutting_down = True
        workflow._acked_ids.add("ack-already-done")
        workflow._pending_outbound.clear()

        await workflow.send_followup_message("ack-already-done", "msg")

        assert workflow._pending_outbound == [
            OutboundSignal(
                target_signal=PARENT_ACK_SIGNAL,
                args=["send_followup_message", "ack-already-done", True, None],
                correlation_id="ack-already-done",
            )
        ]


class TestRunStatusTransitions:
    """The TaskRun must remain in_progress on successful completion *and* on
    inactivity timeout — it stays followable. Only an explicit failure or
    cancellation propagated via complete_task transitions it out."""

    @pytest.mark.parametrize(
        "completion_status, expected_call",
        [
            ("completed", None),
            ("failed", ("failed", "details")),
            ("cancelled", ("cancelled", "details")),
        ],
    )
    async def test_only_records_failed_or_cancelled(
        self, monkeypatch, silent_workflow_logger, completion_status, expected_call
    ):
        workflow = ExecuteSandboxWorkflow()
        workflow._context = _build_context()
        workflow._task_completed = True
        workflow._completion_status = completion_status
        workflow._completion_error = "details"

        update_status_mock = AsyncMock()
        monkeypatch.setattr(workflow, "_update_task_run_status", update_status_mock)

        await workflow._maybe_record_terminal_status()

        if expected_call is None:
            update_status_mock.assert_not_awaited()
        else:
            status, message = expected_call
            update_status_mock.assert_awaited_once_with(status, error_message=message, error_type=None)


class TestCompletionStatusOnExceptionPaths:
    """The terminal completion signal's `success` flag is derived from
    `_completion_status`, so the cancel / exception paths must set it —
    otherwise the orchestrator would see `success=True` for a run that
    actually died."""

    async def test_cancelled_run_signals_success_false_with_cancelled_marker(self, monkeypatch, silent_workflow_logger):
        workflow = ExecuteSandboxWorkflow()
        get_context_mock = AsyncMock(side_effect=asyncio.CancelledError())
        monkeypatch.setattr(workflow, "_get_task_processing_context", get_context_mock)
        monkeypatch.setattr(workflow, "_update_task_run_status", AsyncMock())
        monkeypatch.setattr(workflow, "_track_workflow_event", AsyncMock())
        monkeypatch.setattr(workflow, "_reap_orphaned_sandbox", AsyncMock())
        monkeypatch.setattr(workflow, "_flush_pending_outbound", AsyncMock())

        with pytest.raises(asyncio.CancelledError):
            await workflow.run(ExecuteSandboxInput(run_id="run-id", parent_workflow_id="parent-wf-id"))

        # `_completion_status` flipped to "cancelled" in the except branch
        # so the finally block's enqueued completion payload reports
        # `success=False`.
        assert workflow._completion_status == "cancelled"
        # The payload was enqueued for the orchestrator with success=False.
        completed_signals = [
            outbound for outbound in workflow._pending_outbound if outbound.target_signal == PARENT_COMPLETED_SIGNAL
        ]
        assert len(completed_signals) == 1
        payload = completed_signals[0].args[0]
        assert isinstance(payload, ChildCompletionPayload)
        assert payload.success is False

    async def test_exception_run_signals_success_false_with_failed_marker(self, monkeypatch, silent_workflow_logger):
        workflow = ExecuteSandboxWorkflow()
        get_context_mock = AsyncMock(side_effect=RuntimeError("db down"))
        monkeypatch.setattr(workflow, "_get_task_processing_context", get_context_mock)
        monkeypatch.setattr(workflow, "_update_task_run_status", AsyncMock())
        monkeypatch.setattr(workflow, "_track_workflow_event", AsyncMock())
        monkeypatch.setattr(workflow, "_reap_orphaned_sandbox", AsyncMock())
        monkeypatch.setattr(workflow, "_flush_pending_outbound", AsyncMock())

        result = await workflow.run(ExecuteSandboxInput(run_id="run-id", parent_workflow_id="parent-wf-id"))

        assert result.success is False
        assert workflow._completion_status == "failed"
        assert workflow._completion_error == "db down"
        completed_signals = [
            outbound for outbound in workflow._pending_outbound if outbound.target_signal == PARENT_COMPLETED_SIGNAL
        ]
        assert len(completed_signals) == 1
        payload = completed_signals[0].args[0]
        assert isinstance(payload, ChildCompletionPayload)
        assert payload.success is False
        assert payload.error == "db down"
