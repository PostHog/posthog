"""Per-sandbox workflow.

This file is based on `process_task`, most of it is duplicated with a few
changes to support communication between the parent workflow
(`TaskManagementWorkflow`) and itself.

The duplication is used so we don't need to handle patching the original
workflow — the two coexist while we cut traffic over, and `process_task`
is deleted in a later PR.
"""

import json
import asyncio
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Any, Optional

import temporalio
import temporalio.exceptions
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.oauth import PosthogMcpScopes

from products.tasks.backend.services.sandbox import is_public_sandbox_repo
from products.tasks.backend.temporal.constants import (
    INACTIVITY_TIMEOUT,
    OUTBOUND_RETRY_BACKOFF,
    PENDING_MESSAGE_FORWARD_TIMEOUT_SECONDS,
    RELAY_SANDBOX_EVENTS_START_TO_CLOSE_TIMEOUT,
)
from products.tasks.backend.temporal.execute_sandbox.activities.reap_orphaned_sandbox import (
    ReapOrphanedSandboxInput,
    reap_orphaned_sandbox,
)
from products.tasks.backend.temporal.execute_sandbox.activities.sandbox_state import (
    ClearPersistedSandboxIdInput,
    PersistSandboxIdInput,
    clear_persisted_sandbox_id,
    persist_sandbox_id,
)
from products.tasks.backend.temporal.process_task.activities.cleanup_sandbox import CleanupSandboxInput, cleanup_sandbox
from products.tasks.backend.temporal.process_task.activities.create_resume_snapshot import (
    CreateResumeSnapshotInput,
    create_resume_snapshot,
)
from products.tasks.backend.temporal.process_task.activities.emit_progress_activity import (
    EmitProgressInput,
    emit_progress_activity,
)
from products.tasks.backend.temporal.process_task.activities.forward_pending_message import forward_pending_user_message
from products.tasks.backend.temporal.process_task.activities.get_sandbox_for_repository import (
    GetSandboxForRepositoryOutput,
)
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import (
    GetTaskProcessingContextInput,
    TaskProcessingContext,
    get_task_processing_context,
)
from products.tasks.backend.temporal.process_task.activities.provision_sandbox import (
    CheckoutBranchInSandboxInput,
    CloneRepositoryInSandboxInput,
    CreateSandboxForRepositoryInput,
    InjectFreshTokensOnResumeInput,
    PrepareSandboxForRepositoryInput,
    checkout_branch_in_sandbox,
    clone_repository_in_sandbox,
    create_sandbox_for_repository,
    inject_fresh_tokens_on_resume,
    prepare_sandbox_for_repository,
)
from products.tasks.backend.temporal.process_task.activities.read_sandbox_logs import (
    ReadSandboxLogsInput,
    read_sandbox_logs,
)
from products.tasks.backend.temporal.process_task.activities.relay_sandbox_events import (
    RelaySandboxEventsInput,
    relay_sandbox_events,
)
from products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox import (
    SendFollowupToSandboxInput,
    send_followup_to_sandbox,
)
from products.tasks.backend.temporal.process_task.activities.start_agent_server import (
    StartAgentServerInput,
    StartAgentServerOutput,
    start_agent_server,
)
from products.tasks.backend.temporal.process_task.activities.track_workflow_event import (
    TrackWorkflowEventInput,
    track_workflow_event,
)
from products.tasks.backend.temporal.process_task.activities.update_task_run_status import (
    UpdateTaskRunStatusInput,
    update_task_run_status,
)
from products.tasks.backend.temporal.utils import log_on_fail

# Names of signals this workflow sends back to the TaskManagement parent. Kept
# as constants so a rename can be done in one place — and so tests can import
# the exact strings the workflow uses on the wire.
PARENT_ACK_SIGNAL = "execute_sandbox_signal_ack"
PARENT_HEARTBEAT_SIGNAL = "execute_sandbox_heartbeat"
PARENT_COMPLETED_SIGNAL = "execute_sandbox_completed"

# Name of the bootstrap signal the orchestrator uses with Signal-With-Start.
# Kept here (not in `task_management`) because it's part of *this* workflow's
# inbound signal API.
PARENT_ATTACHED_SIGNAL = "parent_attached"

# Names of the signals the orchestrator delivers to this workflow at runtime.
# Defined here (alongside `PARENT_ATTACHED_SIGNAL`) so a rename on either side
# stays in lockstep — the orchestrator imports these strings rather than
# inlining them at the call site.
COMPLETE_TASK_SIGNAL = "complete_task"
SEND_FOLLOWUP_SIGNAL = "send_followup_message"
# Inbound heartbeat from the in-workflow relay activity. Heartbeats only ever
# flow child -> parent; the orchestrator never signals this.
HEARTBEAT_SIGNAL = "heartbeat"

# Detail string returned in an ACK rejection when the child is mid-cleanup.
# The orchestrator branches on this exact value in `_handle_shutdown_rejection`
# to decide whether to re-queue the follow-up for the next sandbox session.
SHUTDOWN_REJECTION_DETAIL = "child_shutting_down"

# Followup source labels. The child treats both identically (it dispatches
# whatever the orchestrator tells it); the orchestrator uses them to log and
# to drive CI-vs-user-message metrics.
FOLLOWUP_SOURCE_USER = "user"
FOLLOWUP_SOURCE_CI = "ci"


@dataclass
class ExecuteSandboxInput:
    run_id: str
    # Workflow id of the TaskManagement parent. Required: this workflow only
    # accepts instructions from that parent and ACKs back to it. We accept it
    # explicitly (rather than reading workflow.info().parent) so the workflow
    # can also be started standalone in tests with a stub parent id.
    parent_workflow_id: str
    create_pr: bool = True
    slack_thread_context: Optional[dict[str, Any]] = None
    posthog_mcp_scopes: PosthogMcpScopes = "read_only"


@dataclass
class ExecuteSandboxOutput:
    success: bool
    error: Optional[str] = None
    sandbox_id: Optional[str] = None
    timed_out: bool = False


@dataclass
class PendingFollowup:
    """A follow-up message queued by the parent workflow.

    `ack_id` is echoed back to the parent once the follow-up has been
    dispatched to the sandbox. `source` is metadata for logs/metrics — the
    child does not branch on it; the parent has already decided.
    """

    message: str | None
    artifact_ids: list[str]
    ack_id: str
    source: str = FOLLOWUP_SOURCE_USER  # FOLLOWUP_SOURCE_USER | FOLLOWUP_SOURCE_CI


@dataclass
class OutboundSignal:
    """A signal queued for delivery to the parent workflow.

    Signal handlers must stay short, so we accumulate outbound signals in a
    list and drain them from the main loop. Used for both ACKs and forwarded
    sandbox events (heartbeats), so the parent has a single delivery path.
    """

    target_signal: str
    args: list[Any]
    # Optional correlation id, useful for logs when an outbound send fails
    # and gets re-queued.
    correlation_id: Optional[str] = None


@dataclass
class ChildCompletionPayload:
    """Terminal-completion payload sent to the orchestrator.

    Single struct so the wire format is one positional arg rather than four,
    and additions (e.g. attaching diagnostic fields later) don't have to
    thread through call sites on both sides.
    """

    success: bool
    error: Optional[str] = None
    sandbox_id: Optional[str] = None
    timed_out: bool = False


class SandboxEvent(StrEnum):
    SIGNAL_RECEIVED = "signal_received"
    TIMEOUT_REACHED = "timeout_reached"


@temporalio.workflow.defn(name="execute-sandbox")
class ExecuteSandboxWorkflow(PostHogWorkflow):
    """Run a single sandbox session for a task run.

    Lifecycle:
      1. Provision the sandbox, clone/checkout, start the agent server.
      2. Start the SSE relay (sandbox -> Redis + heartbeat back into this
         workflow).
      3. Loop on (signal | inactivity timeout). The inactivity timer is the
         only natural end of the sandbox. CI follow-up timing now lives in
         the parent — when a follow-up signal arrives we dispatch it
         unconditionally and ACK.
      4. Cleanup: snapshot (if interactive resume is on), drain logs, cleanup
         sandbox.

    Communication contract with TaskManagement (parent):
      * Parent -> child: signals (complete_task, send_followup_message).
        Each carries an `ack_id`. The parent never sends heartbeats — they
        only flow child -> parent.
      * Child -> parent: an ACK signal (`PARENT_ACK_SIGNAL`) for every signal
        the parent sent, after the corresponding work has been queued or
        completed on the child side.
      * Sandbox events are forwarded via the existing relay activity (Redis
        stream + workflow heartbeats), not directly into the parent.
    """

    def __init__(self) -> None:
        self._context: Optional[TaskProcessingContext] = None
        self._slack_thread_context: Optional[dict[str, Any]] = None
        self._posthog_mcp_scopes: PosthogMcpScopes = "read_only"
        self._parent_workflow_id: Optional[str] = None
        self._sandbox_id_for_cleanup: Optional[str] = None

        self._task_completed: bool = False
        self._completion_status: str = "completed"
        self._completion_error: Optional[str] = None

        self._heartbeat_received: bool = False
        self._pending_followups: list[PendingFollowup] = []
        self._pending_outbound: list[OutboundSignal] = []

        # Set in the `finally` block before we start emitting the terminal
        # completion signal. While true, signal handlers that would otherwise
        # queue new work (`send_followup_message`, `complete_task`) reject
        # back to the parent so it knows to spin up a fresh sandbox rather
        # than waiting for in-flight work that will never run.
        self._shutting_down: bool = False

        # Dedupes inbound signals on `ack_id`. The orchestrator re-sends
        # signals when an ACK doesn't come back in time, so the child must
        # treat re-deliveries as idempotent — re-ack the original outcome
        # and skip the side-effects.
        self._acked_ids: set[str] = set()

        # Tracks follow-up ack_ids currently being dispatched (popped from
        # `_pending_followups` but not yet ACKed). A retry that arrives while
        # the original is mid-`send_followup_to_sandbox` is dropped silently
        # here; the original's ACK will go out at dispatch completion and
        # the orchestrator's slot will match it.
        self._in_flight_followup_ack_ids: set[str] = set()

        self._current_progress_step: Optional[tuple[str, str, str]] = None

    @property
    def context(self) -> TaskProcessingContext:
        if self._context is None:
            raise RuntimeError("context accessed before being set")
        return self._context

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ExecuteSandboxInput:
        loaded = json.loads(inputs[0])
        return ExecuteSandboxInput(
            run_id=loaded["run_id"],
            parent_workflow_id=loaded["parent_workflow_id"],
            create_pr=loaded.get("create_pr", True),
            slack_thread_context=loaded.get("slack_thread_context"),
            posthog_mcp_scopes=loaded.get("posthog_mcp_scopes", "read_only"),
        )

    @staticmethod
    def _activity_error_properties(error: Exception) -> dict[str, Any]:
        if not isinstance(error, temporalio.exceptions.ActivityError):
            return {}

        retry_state = error.retry_state
        properties: dict[str, Any] = {
            "temporal_activity_id": error.activity_id,
            "temporal_activity_type": error.activity_type,
            "temporal_activity_identity": error.identity,
            "temporal_activity_retry_state": retry_state.name if retry_state else None,
            "temporal_activity_scheduled_event_id": error.scheduled_event_id,
            "temporal_activity_started_event_id": error.started_event_id,
        }
        if error.cause:
            properties.update(
                {
                    "cause_error_type": type(error.cause).__name__,
                    "cause_error_message": str(error.cause)[:500],
                }
            )
        return properties

    @staticmethod
    def _should_skip_followup(message: str | None, artifact_ids: list[str]) -> bool:
        return not message and not artifact_ids

    # ------------------------------------------------------------------
    # Event-wait loop
    # ------------------------------------------------------------------

    async def _wait_for_signal(self) -> SandboxEvent:
        await workflow.wait_condition(
            lambda: self._task_completed
            or self._heartbeat_received
            or len(self._pending_followups) > 0
            or len(self._pending_outbound) > 0
        )
        return SandboxEvent.SIGNAL_RECEIVED

    async def _wait_for_inactivity(self) -> SandboxEvent:
        await workflow.sleep(INACTIVITY_TIMEOUT.total_seconds())
        return SandboxEvent.TIMEOUT_REACHED

    async def _wait_for_event(self) -> SandboxEvent:
        possible_events: list[asyncio.Task[SandboxEvent]] = [
            asyncio.create_task(self._wait_for_signal()),
            asyncio.create_task(self._wait_for_inactivity()),
        ]
        done, pending = await workflow.wait(possible_events, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            if task.exception():
                workflow.logger.warning(
                    "execute_sandbox_event_wait_failed",
                    run_id=self.context.run_id,
                    error=str(task.exception()),
                )
                continue
            return task.result()
        raise RuntimeError("No event completed successfully")

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------

    @workflow.run
    async def run(self, input: ExecuteSandboxInput) -> ExecuteSandboxOutput:
        sandbox_id: Optional[str] = None
        timed_out = False
        run_id = input.run_id

        self._parent_workflow_id = input.parent_workflow_id
        self._slack_thread_context = input.slack_thread_context
        self._sandbox_id_for_cleanup = None

        try:
            # Reap any orphaned sandbox left by a prior execution under this
            # workflow id. Safe because Signal-With-Start + ALLOW_DUPLICATE
            # only let a new execution start once the prior one is closed —
            # so anything we find in state belongs to a dead workflow.
            await self._reap_orphaned_sandbox(run_id)

            self._context = await self._get_task_processing_context(input)
            self._posthog_mcp_scopes = input.posthog_mcp_scopes

            await self._update_task_run_status("in_progress")
            await self._emit_progress("sandbox", "in_progress", "Setting up sandbox", "setup")
            await self._track_workflow_event(
                "task_run_started",
                {
                    "run_id": run_id,
                    "task_id": self.context.task_id,
                    "repository": self.context.repository,
                    "team_id": self.context.team_id,
                },
            )

            sandbox_output = await self._get_sandbox_for_repository()
            sandbox_id = sandbox_output.sandbox_id
            # Persist before anything else can fail — keeps the reaper window
            # to the gap between Modal-accepted-create and this activity.
            await self._persist_sandbox_id(run_id, sandbox_id)

            await self._emit_progress("agent", "in_progress", "Starting agent", "setup")
            agent_server_output = await self._start_agent_server(sandbox_output)
            await self._emit_progress("agent", "completed", "Started agent", "setup")

            await self._track_workflow_event(
                "sandbox_started",
                {
                    "run_id": run_id,
                    "task_id": self.context.task_id,
                    "sandbox_id": sandbox_id,
                    "sandbox_url": agent_server_output.sandbox_url,
                    "used_snapshot": sandbox_output.used_snapshot,
                    "repository": self.context.repository,
                },
            )

            relay_task = asyncio.ensure_future(self._relay_sandbox_events(agent_server_output, sandbox_id=sandbox_id))

            if self._should_forward_pending_user_message():
                await self._forward_pending_user_message()

            # Main loop: hand control between signal-driven work and the
            # inactivity timer. The timer is the only natural end of the
            # sandbox; the parent decides CI follow-up timing and sends them
            # to us as plain follow-up signals.
            while not self._task_completed:
                event = await self._wait_for_event()
                match event:
                    case SandboxEvent.TIMEOUT_REACHED:
                        timed_out = True
                        break
                    case SandboxEvent.SIGNAL_RECEIVED:
                        # complete_task lands here too — `_flush_pending_outbound`
                        # delivers its ACK and the `while not self._task_completed:`
                        # check at the top of the loop exits us on the next pass.
                        await self._flush_pending_outbound()

                        if self._pending_followups:
                            followup = self._pending_followups.pop(0)
                            await self._handle_followup(followup)
                            continue

                        if self._heartbeat_received and not self._task_completed:
                            workflow.logger.info(
                                "execute_sandbox_heartbeat_reset",
                                run_id=self.context.run_id,
                            )
                            self._heartbeat_received = False
                            continue
                    case _:
                        raise ValueError(f"Unknown sandbox event: {event}")

            await self._cancel_relay(relay_task)
            # Drain any outbound signals that landed during shutdown so the
            # parent never waits on a signal we silently dropped.
            await self._flush_pending_outbound()

            await self._maybe_record_terminal_status()

            return ExecuteSandboxOutput(
                success=True,
                error=None,
                sandbox_id=sandbox_id,
                timed_out=timed_out,
            )

        except asyncio.CancelledError:
            # Reflect cancellation in the terminal completion signal — the
            # `finally` block reads `_completion_status` to decide the
            # `success` flag. Without this, an orchestrator would see
            # `success=True` for a cancelled run.
            self._completion_status = "cancelled"
            self._completion_error = "Workflow cancelled"
            current_sandbox_id = sandbox_id or self._sandbox_id_for_cleanup
            if self._context:
                if self._current_progress_step is not None:
                    failed_step, failed_label, failed_group = self._current_progress_step
                    await self._emit_progress(failed_step, "failed", failed_label, failed_group, detail="Cancelled")
                await self._track_workflow_event(
                    "task_run_cancelled",
                    {
                        "run_id": run_id,
                        "task_id": self.context.task_id,
                        "repository": self.context.repository,
                        "team_id": self.context.team_id,
                    },
                )
            await self._update_task_run_status("cancelled", run_id=run_id)
            if current_sandbox_id:
                await self._cleanup_sandbox(current_sandbox_id)
                sandbox_id = None
                self._sandbox_id_for_cleanup = None
            raise

        except Exception as e:
            # Same reasoning as the CancelledError branch — the `finally`
            # block's completion signal reads `_completion_status`; without
            # setting it here the orchestrator would see `success=True` for
            # a run that died on an unhandled exception.
            self._completion_status = "failed"
            self._completion_error = str(e)[:500]
            current_sandbox_id = sandbox_id or self._sandbox_id_for_cleanup
            error_message = str(e)[:500]
            if self._context:
                if self._current_progress_step is not None:
                    failed_step, failed_label, failed_group = self._current_progress_step
                    await self._emit_progress(
                        failed_step, "failed", failed_label, failed_group, detail=error_message[:200]
                    )
                await self._track_workflow_event(
                    "task_run_failed",
                    {
                        "run_id": run_id,
                        "task_id": self.context.task_id,
                        "repository": self.context.repository,
                        "origin_product": self.context.origin_product,
                        "environment": self.context.environment,
                        "mode": self.context.mode,
                        "run_source": self.context.run_source,
                        "runtime_adapter": self.context.runtime_adapter,
                        "provider": self.context.provider,
                        "model": self.context.model,
                        "reasoning_effort": self.context.reasoning_effort,
                        "error_type": type(e).__name__,
                        "error_message": error_message,
                        "sandbox_id": current_sandbox_id,
                        **self._activity_error_properties(e),
                    },
                )
            await self._update_task_run_status("failed", error_message=error_message, run_id=run_id)

            return ExecuteSandboxOutput(
                success=False,
                error=error_message,
                sandbox_id=current_sandbox_id,
                timed_out=False,
            )

        finally:
            # Flip the shutdown flag before any cleanup awaits. Late-arriving
            # `send_followup_message` / `complete_task` signals from this
            # point on are rejected so the orchestrator's retry path can
            # route them to a fresh sandbox instead of waiting on us.
            self._shutting_down = True

            cleanup_sandbox_id = sandbox_id or self._sandbox_id_for_cleanup
            if cleanup_sandbox_id:
                if self._context and self._context.mode == "interactive" and self._context.use_modal_resume_snapshots:
                    await self._create_resume_snapshot(cleanup_sandbox_id)

                await self._read_sandbox_logs(cleanup_sandbox_id)
                await self._cleanup_sandbox(cleanup_sandbox_id)
                # Clear the persisted sandbox id only after cleanup actually
                # ran — otherwise the next workflow start has no record of an
                # orphan to reap.
                await self._clear_persisted_sandbox_id(run_id)
                self._sandbox_id_for_cleanup = None

            # Emit the terminal "I'm done" signal to the orchestrator before
            # the final outbound flush so it goes through the same retry
            # machinery as everything else.
            self._enqueue_completed_signal(
                ChildCompletionPayload(
                    success=self._completion_status not in {"failed", "cancelled"},
                    error=self._completion_error,
                    sandbox_id=cleanup_sandbox_id,
                    timed_out=timed_out,
                )
            )
            # Final outbound flush — the parent should never be left waiting
            # on a signal we accepted but never acknowledged.
            await self._flush_pending_outbound()

    # ------------------------------------------------------------------
    # Signal handlers — keep these short. They only mutate state; the main
    # loop drains queues and performs the actual work + ACK.
    # ------------------------------------------------------------------

    @workflow.signal(name=PARENT_ATTACHED_SIGNAL)
    async def parent_attached(self, ack_id: str, parent_workflow_id: str) -> None:
        """Bootstrap signal delivered via Signal-With-Start.

        Idempotent: the parent_workflow_id is deterministic, so re-attach by a
        restarted orchestrator is a no-op. Sending an ACK confirms to the
        parent that the workflow is alive and processing signals.
        """
        if self._is_duplicate_signal(PARENT_ATTACHED_SIGNAL, ack_id):
            return
        self._parent_workflow_id = parent_workflow_id
        self._enqueue_ack(signal_name=PARENT_ATTACHED_SIGNAL, ack_id=ack_id)

    @workflow.signal(name=COMPLETE_TASK_SIGNAL)
    async def complete_task(
        self,
        ack_id: str,
        status: str = "completed",
        error_message: Optional[str] = None,
    ) -> None:
        # Orchestrator re-sent because the original ACK was lost — re-ack
        # idempotently and don't reapply completion state.
        if self._is_duplicate_signal(COMPLETE_TASK_SIGNAL, ack_id):
            return
        if self._shutting_down:
            # We're already in the cleanup path; the orchestrator will see
            # the completion signal we're about to emit. Reject this so it
            # doesn't keep waiting on a slot we'll never honour.
            self._enqueue_ack(
                signal_name=COMPLETE_TASK_SIGNAL,
                ack_id=ack_id,
                accepted=False,
                detail=SHUTDOWN_REJECTION_DETAIL,
            )
            return
        self._completion_status = status
        self._completion_error = error_message
        self._task_completed = True
        self._enqueue_ack(signal_name=COMPLETE_TASK_SIGNAL, ack_id=ack_id)

    @workflow.signal(name=SEND_FOLLOWUP_SIGNAL)
    async def send_followup_message(
        self,
        ack_id: str,
        message: str | None = None,
        artifact_ids: Optional[list[str]] = None,
        source: str = FOLLOWUP_SOURCE_USER,
    ) -> None:
        """Accept a follow-up message from the parent and queue it.

        Whether this is a user-driven message or a CI prompt is decided by
        the parent; the `source` value is only used for logs/metrics. The
        child always dispatches what it is told.
        """
        context = self._context
        workflow.logger.info(
            "execute_sandbox_followup_signal_received",
            run_id=context.run_id if context is not None else None,
            message_length=len(message or ""),
            artifact_count=len(artifact_ids or []),
            source=source,
            ack_id=ack_id,
        )
        # Already dispatched (or rejected) — re-ack and skip.
        if self._is_duplicate_signal(SEND_FOLLOWUP_SIGNAL, ack_id):
            return
        if any(p.ack_id == ack_id for p in self._pending_followups) or ack_id in self._in_flight_followup_ack_ids:
            # Still in flight from the first delivery (queued, or popped and
            # mid-dispatch) — the original will ACK shortly. Drop the
            # duplicate quietly so we don't double-send to the sandbox.
            return
        if self._shutting_down:
            # Reject the follow-up so the orchestrator's retry path can
            # route it to a fresh sandbox instead of waiting indefinitely
            # on a child that has already torn down its session.
            self._enqueue_ack(
                signal_name=SEND_FOLLOWUP_SIGNAL,
                ack_id=ack_id,
                accepted=False,
                detail=SHUTDOWN_REJECTION_DETAIL,
            )
            return
        self._pending_followups.append(
            PendingFollowup(
                message=message,
                artifact_ids=artifact_ids or [],
                ack_id=ack_id,
                source=source,
            )
        )

    @workflow.signal(name=HEARTBEAT_SIGNAL)
    async def heartbeat(self, agent_active: bool = False) -> None:
        """Heartbeat from the relay activity.

        Heartbeats only ever flow child -> parent: the in-workflow relay
        signals us, we record activity locally and forward to the parent
        (`PARENT_HEARTBEAT_SIGNAL`) so it can drive its own CI follow-up
        timing without relaying through the sandbox twice. The parent is
        expected to debounce on its side.
        """
        self._heartbeat_received = True
        self._pending_outbound.append(OutboundSignal(target_signal=PARENT_HEARTBEAT_SIGNAL, args=[agent_active]))

    # ------------------------------------------------------------------
    # Follow-up dispatch + ACK plumbing
    # ------------------------------------------------------------------

    async def _handle_followup(self, followup: PendingFollowup) -> None:
        # Mark in-flight synchronously (before any await) so a retry that
        # arrives mid-dispatch sees it via the dedupe check in
        # `send_followup_message` and is dropped quietly.
        self._in_flight_followup_ack_ids.add(followup.ack_id)
        try:
            if self._should_skip_followup(followup.message, followup.artifact_ids):
                workflow.logger.warning(
                    "execute_sandbox_empty_followup_skipped",
                    run_id=self.context.run_id,
                    ack_id=followup.ack_id,
                )
                self._enqueue_ack(
                    signal_name=SEND_FOLLOWUP_SIGNAL,
                    ack_id=followup.ack_id,
                    accepted=False,
                    detail="empty follow-up skipped",
                )
                return

            try:
                await self._send_followup_to_sandbox(
                    message=followup.message,
                    artifact_ids=followup.artifact_ids,
                )
                self._enqueue_ack(signal_name=SEND_FOLLOWUP_SIGNAL, ack_id=followup.ack_id)
            except Exception as e:
                # Mirror process_task: a failed follow-up dispatch is terminal.
                # Surface the failure to the parent via both the ACK and the
                # task-completion path so it can react immediately.
                workflow.logger.warning(
                    "execute_sandbox_send_followup_failed",
                    run_id=self.context.run_id,
                    error=str(e),
                )
                self._completion_status = "failed"
                self._completion_error = f"Follow-up delivery failed: {e}"
                self._task_completed = True
                self._enqueue_ack(
                    signal_name=SEND_FOLLOWUP_SIGNAL,
                    ack_id=followup.ack_id,
                    accepted=False,
                    detail=str(e)[:200],
                )
        finally:
            self._in_flight_followup_ack_ids.discard(followup.ack_id)
            await self._flush_pending_outbound()

    def _is_duplicate_signal(self, signal_name: str, ack_id: Optional[str]) -> bool:
        """Detect orchestrator re-sends and re-ack idempotently.

        Returns True when the caller should early-return (already processed).
        Callers pass `None` when the signal didn't carry an ack_id (relay
        heartbeats), in which case nothing is deduped.
        """
        if ack_id is None or ack_id not in self._acked_ids:
            return False
        self._enqueue_ack(signal_name=signal_name, ack_id=ack_id)
        return True

    def _enqueue_ack(
        self,
        signal_name: str,
        ack_id: str,
        accepted: bool = True,
        detail: Optional[str] = None,
    ) -> None:
        """Queue an ACK back to the parent's PARENT_ACK_SIGNAL handler.

        Records the ack_id so future re-deliveries from the orchestrator's
        retry loop are recognised and re-acked without re-running the work.
        """
        self._acked_ids.add(ack_id)
        self._pending_outbound.append(
            OutboundSignal(
                target_signal=PARENT_ACK_SIGNAL,
                args=[signal_name, ack_id, accepted, detail],
                correlation_id=ack_id,
            )
        )

    def _enqueue_completed_signal(self, payload: ChildCompletionPayload) -> None:
        """Queue the terminal completion signal to the orchestrator.

        With ABANDON-style independence (the orchestrator can't `await` us),
        this is the only way the parent learns the run finished. Sent through
        the normal outbound machinery so it gets the same retry behaviour.
        """
        self._pending_outbound.append(
            OutboundSignal(
                target_signal=PARENT_COMPLETED_SIGNAL,
                args=[payload],
            )
        )

    async def _flush_pending_outbound(self) -> None:
        if not self._pending_outbound or not self._parent_workflow_id:
            return
        # Snapshot + clear before awaiting so a signal landing mid-flush
        # doesn't lose its delivery on the next iteration.
        #
        # Ordering note: we keep iterating after a failure, so a later
        # signal that succeeds is delivered before an earlier one that
        # failed and was re-queued. The protocol tolerates this — ACKs
        # match by `ack_id` and PARENT_COMPLETED_SIGNAL is always enqueued
        # last (from the finally block), so it trails any failed signals
        # in the snapshot. Don't "fix" this by breaking after the first
        # failure: that would drop the rest of the snapshot on the floor.
        to_send = self._pending_outbound
        self._pending_outbound = []
        parent = workflow.get_external_workflow_handle(self._parent_workflow_id)
        for outbound in to_send:
            try:
                await parent.signal(outbound.target_signal, args=outbound.args)
            except Exception as e:
                # Don't lose the signal — re-queue and let the next flush
                # retry. If the parent is gone, future flushes will keep
                # failing but the child run is independent and can complete
                # on its own.
                workflow.logger.warning(
                    "execute_sandbox_outbound_signal_failed",
                    run_id=self.context.run_id if self._context else None,
                    target_signal=outbound.target_signal,
                    correlation_id=outbound.correlation_id,
                    error=str(e),
                )
                self._pending_outbound.append(outbound)
        if self._pending_outbound:
            # Re-queued items would otherwise wake the main loop immediately
            # (its wait condition checks `_pending_outbound > 0`) and we'd
            # tight-loop against an unreachable parent, starving the
            # inactivity timer. Sleep to rate-limit retries.
            await workflow.sleep(OUTBOUND_RETRY_BACKOFF.total_seconds())

    # ------------------------------------------------------------------
    # Activities — these mirror process_task's implementations directly so
    # the sandbox lifecycle stays identical. Anything that was about CI
    # decision-making has been removed.
    # ------------------------------------------------------------------

    async def _get_task_processing_context(self, input: ExecuteSandboxInput) -> TaskProcessingContext:
        return await workflow.execute_activity(
            get_task_processing_context,
            GetTaskProcessingContextInput(run_id=input.run_id, create_pr=input.create_pr),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _get_sandbox_for_repository(self) -> GetSandboxForRepositoryOutput:
        prepared = await workflow.execute_activity(
            prepare_sandbox_for_repository,
            PrepareSandboxForRepositoryInput(context=self.context),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        created = await workflow.execute_activity(
            create_sandbox_for_repository,
            CreateSandboxForRepositoryInput(context=self.context, prepared=prepared),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        self._sandbox_id_for_cleanup = created.sandbox_id

        if prepared.used_snapshot:
            await self._emit_progress(
                "sandbox",
                "completed",
                "Restored sandbox",
                "setup",
                detail="Resumed from a previous snapshot",
            )
        else:
            await self._emit_progress("sandbox", "completed", "Set up sandbox", "setup")

        if prepared.snapshot_external_id:
            await workflow.execute_activity(
                inject_fresh_tokens_on_resume,
                InjectFreshTokensOnResumeInput(
                    context=self.context,
                    sandbox_id=created.sandbox_id,
                    repository=prepared.repository,
                ),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

        can_clone_without_integration = is_public_sandbox_repo(prepared.repository)
        has_clone_credentials = self.context.has_github_credentials or can_clone_without_integration

        will_clone = bool(prepared.repository and not prepared.used_snapshot and has_clone_credentials)
        will_checkout = bool(prepared.repository and prepared.branch and has_clone_credentials)

        if will_clone:
            await self._emit_progress("clone", "in_progress", "Cloning repository", "setup")
            await workflow.execute_activity(
                clone_repository_in_sandbox,
                CloneRepositoryInSandboxInput(
                    context=self.context,
                    sandbox_id=created.sandbox_id,
                    repository=prepared.repository,
                    github_token=prepared.github_token,
                    shallow_clone=prepared.shallow_clone,
                ),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            await self._emit_progress("clone", "completed", "Cloned repository", "setup")

        state = self.context.state or {}
        is_resume = bool(state.get("resume_from_run_id") or state.get("handoff_resumed"))
        if will_checkout and not is_resume:
            branch_label_active = f"Checking out branch {prepared.branch}"
            branch_label_done = f"Checked out branch {prepared.branch}"
            await self._emit_progress("checkout", "in_progress", branch_label_active, "setup")
            await workflow.execute_activity(
                checkout_branch_in_sandbox,
                CheckoutBranchInSandboxInput(
                    context=self.context,
                    sandbox_id=created.sandbox_id,
                    repository=prepared.repository,
                    branch=prepared.branch,
                    github_token=prepared.github_token,
                    shallow_clone=prepared.shallow_clone,
                    used_snapshot=prepared.used_snapshot,
                ),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            await self._emit_progress("checkout", "completed", branch_label_done, "setup")

        return GetSandboxForRepositoryOutput(
            sandbox_id=created.sandbox_id,
            sandbox_url=created.sandbox_url,
            connect_token=created.connect_token,
            used_snapshot=prepared.used_snapshot,
            should_create_snapshot=prepared.should_create_snapshot,
        )

    async def _cleanup_sandbox(self, sandbox_id: str) -> None:
        await workflow.execute_activity(
            cleanup_sandbox,
            CleanupSandboxInput(sandbox_id=sandbox_id),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    @log_on_fail("execute_sandbox_reap_failed", level="warning", suppress=True)
    async def _reap_orphaned_sandbox(self, run_id: str) -> None:
        """Destroy any sandbox left by a prior execution under this workflow id.

        Best-effort: Modal-side TTL is the final safety net if destroy itself
        fails inside the activity, and the activity always clears the state
        key — so a stale id staying around doesn't keep retrying a dead
        sandbox on every restart.
        """
        result = await workflow.execute_activity(
            reap_orphaned_sandbox,
            ReapOrphanedSandboxInput(run_id=run_id),
            # Includes the Modal destroy call, so the timeout needs to
            # cover that as well as two DB roundtrips.
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if result.reaped_sandbox_id is not None:
            workflow.logger.info(
                "execute_sandbox_reaped_orphan",
                run_id=run_id,
                sandbox_id=result.reaped_sandbox_id,
                destroy_succeeded=result.destroy_succeeded,
            )

    # Don't fail the run if persistence flakes — Modal TTL will catch the
    # orphan if cleanup is later missed.
    @log_on_fail("execute_sandbox_persist_sandbox_id_failed", level="warning", suppress=True)
    async def _persist_sandbox_id(self, run_id: str, sandbox_id: str) -> None:
        await workflow.execute_activity(
            persist_sandbox_id,
            PersistSandboxIdInput(run_id=run_id, sandbox_id=sandbox_id),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=5),
        )

    # Stale state will be reaped (idempotent) on the next start, so a
    # failure here doesn't compromise correctness.
    @log_on_fail("execute_sandbox_clear_sandbox_id_failed", level="warning", suppress=True)
    async def _clear_persisted_sandbox_id(self, run_id: str) -> None:
        await workflow.execute_activity(
            clear_persisted_sandbox_id,
            ClearPersistedSandboxIdInput(run_id=run_id),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    @log_on_fail("Failed to read sandbox logs", level="warning", suppress=True)
    async def _read_sandbox_logs(self, sandbox_id: str) -> None:
        logs = await workflow.execute_activity(
            read_sandbox_logs,
            ReadSandboxLogsInput(sandbox_id=sandbox_id, run_id=self.context.run_id),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        if logs:
            workflow.logger.info(f"Agent-server logs from sandbox {sandbox_id}:\n{logs}")

    async def _start_agent_server(self, sandbox_output: GetSandboxForRepositoryOutput) -> StartAgentServerOutput:
        return await workflow.execute_activity(
            start_agent_server,
            StartAgentServerInput(
                context=self.context,
                sandbox_id=sandbox_output.sandbox_id,
                sandbox_url=sandbox_output.sandbox_url,
                sandbox_connect_token=sandbox_output.connect_token,
                posthog_mcp_scopes=self._posthog_mcp_scopes,
            ),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _forward_pending_user_message(self) -> None:
        await workflow.execute_activity(
            forward_pending_user_message,
            self.context.run_id,
            start_to_close_timeout=timedelta(seconds=PENDING_MESSAGE_FORWARD_TIMEOUT_SECONDS),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

    def _should_forward_pending_user_message(self) -> bool:
        if not self._context:
            return False
        state = self.context.state or {}
        is_resume = bool(state.get("resume_from_run_id") or state.get("handoff_resumed"))
        return self.context.mode != "interactive" and not is_resume

    async def _track_workflow_event(self, event_name: str, properties: dict) -> None:
        await workflow.execute_activity(
            track_workflow_event,
            TrackWorkflowEventInput(
                event_name=event_name,
                distinct_id=self.context.distinct_id,
                properties=properties,
                groups={
                    "organization": self.context.organization_id,
                    "project": self.context.team_uuid,
                },
            ),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

    @log_on_fail("execute_sandbox_emit_progress_failed", level="warning", suppress=True)
    async def _emit_progress(
        self,
        step: str,
        status: str,
        label: str,
        group: str,
        detail: Optional[str] = None,
    ) -> None:
        scoped_group = f"{group}:{self.context.run_id}"
        await workflow.execute_activity(
            emit_progress_activity,
            EmitProgressInput(
                run_id=self.context.run_id,
                step=step,
                status=status,
                label=label,
                group=scoped_group,
                detail=detail,
            ),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        if status == "in_progress":
            self._current_progress_step = (step, label, group)
        elif status in {"completed", "failed"}:
            if self._current_progress_step and self._current_progress_step[0] == step:
                self._current_progress_step = None

    async def _update_task_run_status(
        self,
        status: str,
        error_message: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> None:
        await workflow.execute_activity(
            update_task_run_status,
            UpdateTaskRunStatusInput(
                run_id=run_id if run_id is not None else self.context.run_id,
                status=status,
                error_message=error_message,
            ),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _maybe_record_terminal_status(self) -> None:
        # TaskRun stays in_progress on successful completion *and* on
        # inactivity timeout — the run is always followable, so neither
        # path is terminal. Only an explicit failure or cancellation
        # propagated through complete_task transitions out of in_progress;
        # the except blocks in run() cover the other terminal paths.
        if self._task_completed and self._completion_status in {"failed", "cancelled"}:
            await self._update_task_run_status(self._completion_status, error_message=self._completion_error)

    # `log_on_fail` only catches `Exception`, so `asyncio.CancelledError`
    # (a `BaseException`) still propagates — required for cooperative
    # cancellation of the relay task on shutdown.
    @log_on_fail("execute_sandbox_relay_failed_non_fatal", level="warning", suppress=True)
    async def _relay_sandbox_events(
        self,
        agent_server_output: StartAgentServerOutput,
        sandbox_id: str | None = None,
    ) -> None:
        await workflow.execute_activity(
            relay_sandbox_events,
            RelaySandboxEventsInput(
                run_id=self.context.run_id,
                task_id=self.context.task_id,
                sandbox_url=agent_server_output.sandbox_url,
                sandbox_connect_token=agent_server_output.connect_token,
                team_id=self.context.team_id,
                distinct_id=self.context.distinct_id,
                sandbox_id=sandbox_id,
            ),
            start_to_close_timeout=RELAY_SANDBOX_EVENTS_START_TO_CLOSE_TIMEOUT,
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=1),
            cancellation_type=workflow.ActivityCancellationType.TRY_CANCEL,
        )

    @staticmethod
    async def _cancel_relay(relay_task: "asyncio.Task[None]") -> None:
        if relay_task.done():
            return
        relay_task.cancel()
        try:
            await relay_task
        except (asyncio.CancelledError, Exception):
            pass

    @log_on_fail("Resume snapshot failed (non-fatal)", level="warning", suppress=True)
    async def _create_resume_snapshot(self, sandbox_id: str) -> None:
        result = await workflow.execute_activity(
            create_resume_snapshot,
            CreateResumeSnapshotInput(sandbox_id=sandbox_id, run_id=self.context.run_id),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        if result.external_id:
            workflow.logger.info(f"Resume snapshot created: {result.external_id} for sandbox {sandbox_id}")
        elif result.error:
            workflow.logger.warning(f"Resume snapshot skipped: {result.error}")

    async def _send_followup_to_sandbox(self, message: str | None, artifact_ids: list[str]) -> None:
        workflow.logger.info(
            "execute_sandbox_send_followup_begin",
            run_id=self.context.run_id,
            message_length=len(message or ""),
            artifact_count=len(artifact_ids),
        )
        await workflow.execute_activity(
            send_followup_to_sandbox,
            SendFollowupToSandboxInput(
                run_id=self.context.run_id,
                message=message,
                posthog_mcp_scopes=self._posthog_mcp_scopes,
                artifact_ids=artifact_ids,
            ),
            start_to_close_timeout=timedelta(minutes=35),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
