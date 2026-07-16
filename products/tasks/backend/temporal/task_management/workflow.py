import json
import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Optional

import temporalio
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.oauth import PosthogMcpScopes

from products.tasks.backend.error_telemetry import truncate_error_message
from products.tasks.backend.temporal.constants import (
    ACK_TIMEOUT,
    CI_FOLLOW_UP_DELAY,
    DEFAULT_CI_MESSAGE,
    HEARTBEAT_DEBOUNCE,
    MAX_ACK_RETRIES,
    MAX_CI_REPETITIONS,
    SEND_STEER_SIGNAL,
    STEERING_PROTOCOL_QUERY,
    STEERING_PROTOCOL_VERSION,
)
from products.tasks.backend.temporal.execute_sandbox.workflow import (
    COMPLETE_TASK_SIGNAL,
    FOLLOWUP_SOURCE_CI,
    FOLLOWUP_SOURCE_USER,
    PARENT_ACK_SIGNAL,
    PARENT_ATTACHED_SIGNAL,
    PARENT_COMPLETED_SIGNAL,
    PARENT_HEARTBEAT_SIGNAL,
    SEND_FOLLOWUP_SIGNAL,
    SHUTDOWN_REJECTION_DETAIL,
    ChildCompletionPayload,
    ExecuteSandboxInput,
)
from products.tasks.backend.temporal.process_task.activities.get_pr_context import GetPrContextInput, get_pr_context
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import (
    GetTaskProcessingContextInput,
    TaskProcessingContext,
    get_task_processing_context,
)
from products.tasks.backend.temporal.process_task.activities.post_slack_update import (
    PostSlackUpdateInput,
    post_slack_update,
)
from products.tasks.backend.temporal.process_task.activities.track_workflow_event import (
    TrackWorkflowEventInput,
    track_workflow_event,
)
from products.tasks.backend.temporal.process_task.activities.update_task_run_status import (
    UpdateTaskRunStatusInput,
    update_task_run_status,
)
from products.tasks.backend.temporal.task_management.activities.ensure_execute_sandbox_started import (
    EnsureExecuteSandboxStartedInput,
    ensure_execute_sandbox_started,
)
from products.tasks.backend.temporal.task_management.activities.pending_followups import (
    PersistPendingFollowupsInput,
    ReadPendingFollowupsInput,
    persist_pending_followups,
    read_pending_followups,
)

_PATCH_ID_CAPABILITY_GATED_STEERING = "tasks-capability-gated-steering-signal"
_PATCH_ID_ACK_BEFORE_COMPLETION = "tasks-task-management-ack-before-completion"
_PATCH_ID_ACK_BEFORE_COMPLETION_SANDBOX_GENERATION = "tasks-task-management-ack-before-completion-sandbox-generation"
_PATCH_ID_CLOSED_CHILD_FOLLOWUP_RECOVERY = "tasks-task-management-closed-child-followup-recovery"
_PATCH_ID_CLOSED_CHILD_COMPLETION_RECOVERY = "tasks-task-management-closed-child-completion-recovery"
_PATCH_ID_CLOSED_CHILD_ACK_RETRY_RECOVERY = "tasks-task-management-closed-child-ack-retry-recovery"
_PATCH_ID_CLEAR_STEER_ON_SANDBOX_BOUNDARY = "tasks-task-management-clear-steer-on-sandbox-boundary"
_PATCH_ID_BOUNDED_SANDBOX_REPLACEMENT_RECOVERY = "tasks-task-management-bounded-sandbox-replacement-recovery"
_PATCH_ID_PERSIST_REPLACEMENT_BUDGET = "tasks-task-management-persist-replacement-budget"
_PATCH_ID_ACCEPTED_ACK_RESETS_REPLACEMENT_BUDGET = "tasks-task-management-accepted-ack-resets-replacement-budget"
_CHILD_SIGNAL_TERMINAL_ERROR_TYPES = {
    "ExternalWorkflowExecutionNotFound",
    "NamespaceNotFound",
}
MAX_CONSECUTIVE_SANDBOX_REPLACEMENT_FAILURES = 5
MAX_SANDBOX_REPLACEMENT_BACKOFF_SECONDS = 30


def _ack_before_completion() -> bool:
    if not workflow.in_workflow():
        return True
    return workflow.patched(_PATCH_ID_ACK_BEFORE_COMPLETION)


def _ack_before_completion_for_sandbox_generation(generation: int) -> bool:
    if not workflow.in_workflow():
        return True
    return workflow.patched(f"{_PATCH_ID_ACK_BEFORE_COMPLETION_SANDBOX_GENERATION}-{generation}")


def _patch_enabled(patch_id: str) -> bool:
    if not workflow.in_workflow():
        return True
    return workflow.patched(patch_id)


def _child_cannot_receive_signals(error: Exception) -> bool:
    return (
        isinstance(error, temporalio.exceptions.ApplicationError) and error.type in _CHILD_SIGNAL_TERMINAL_ERROR_TYPES
    )


@dataclass
class TaskRunManagementInput:
    run_id: str
    create_pr: bool = True
    slack_thread_context: Optional[dict[str, Any]] = None
    posthog_mcp_scopes: PosthogMcpScopes = "read_only"


@dataclass
class TaskRunManagementOutput:
    success: bool
    error: Optional[str] = None
    sandbox_id: Optional[str] = None
    timed_out: bool = False
    ci_repetitions: int = 0


@dataclass
class PendingExternalFollowup:
    """A follow-up queued by an external caller (API, Slack, runner)."""

    message: str | None
    artifact_ids: list[str]
    source: str = FOLLOWUP_SOURCE_USER  # FOLLOWUP_SOURCE_USER | FOLLOWUP_SOURCE_CI
    steer: bool = False
    sequence: int = 0


@dataclass
class ChildAck:
    """One ACK from the child workflow."""

    signal_name: str
    ack_id: str
    accepted: bool
    detail: Optional[str]
    received_at: datetime


@dataclass
class ChildCompletion:
    """Terminal result reported by the child via PARENT_COMPLETED_SIGNAL."""

    success: bool
    error: Optional[str]
    sandbox_id: Optional[str]
    timed_out: bool


@dataclass
class PendingAckSlot:
    """Tracks a signal we sent to the child while we wait for the ACK.

    `signal_args` is the full positional arg list for the original
    `handle.signal(signal_name, args=...)` call, so the retry loop can
    re-send identical bytes — the child uses `signal_args[0]` (ack_id) to
    dedupe. Bootstrap slots leave `signal_args=None` because re-signaling
    `parent_attached` directly isn't useful (the activity already retried);
    those slots are dropped after timeout instead of retried.
    """

    signal_name: str
    sent_at: datetime
    detail: Optional[str] = None
    signal_args: Optional[list[Any]] = None
    retry_count: int = 0
    sequence: int = 0


class TaskEvent(StrEnum):
    EXTERNAL_SIGNAL = "external_signal"
    CHILD_FORWARDED = "child_forwarded"
    CI_FOLLOW_UP_DUE = "ci_follow_up_due"
    CHILD_COMPLETED = "child_completed"
    ACK_RETRY_DUE = "ack_retry_due"


class CIFollowUpDecision(StrEnum):
    FIRE = "fire"
    SKIP = "skip"
    NO_PR = "no_pr"


@temporalio.workflow.defn(name="task-management")
class TaskManagementWorkflow(PostHogWorkflow):
    """Top-level orchestrator for a task run.

    Owns:
      * Bootstrapping the ExecuteSandbox workflow via Signal-With-Start under
        a deterministic workflow id derived from our own id. ExecuteSandbox
        runs as an independent workflow (not a Temporal child), so it
        survives a restart of this orchestrator.
      * CI follow-up timing — decides whether to send a CI prompt and
        dispatches it as a regular follow-up signal to the sandbox workflow.
      * Forwarding of external signals (from API, Slack, multi-turn runner)
        into the sandbox workflow, with ACK tracking.

    External callers signal *this* workflow under the stable workflow id
    `TaskRun.get_workflow_id(task_id, run_id)`. The sandbox workflow id is
    derived from ours so the two are always associated.
    """

    SANDBOX_WORKFLOW_NAME = "execute-sandbox"

    def __init__(self) -> None:
        self._context: Optional[TaskProcessingContext] = None
        self._slack_thread_context: Optional[dict[str, Any]] = None
        self._posthog_mcp_scopes: PosthogMcpScopes = "read_only"
        self._run_id: Optional[str] = None
        self._create_pr: bool = True

        # External signals (from API, Slack, runner) queued for delivery to
        # the sandbox workflow. We assign ack_ids when we forward.
        self._pending_external_followups: list[PendingExternalFollowup] = []
        self._next_followup_sequence: int = 0
        self._pending_external_complete: Optional[tuple[str, Optional[str]]] = None
        # Last payload we wrote to TaskRun.state, so `_persist_pending_followups`
        # can skip the DB roundtrip when nothing changed (e.g., draining an
        # already-empty queue still triggers a persist call).
        self._last_persisted_followups: list[dict[str, Any]] = []

        # Sandbox-side state.
        self._sandbox_workflow_id: Optional[str] = None
        self._child_acks: list[ChildAck] = []
        self._pending_ack_slots: dict[str, PendingAckSlot] = {}
        self._child_completion: Optional[ChildCompletion] = None
        self._ack_before_completion: bool = True
        self._sandbox_generation: int = 0
        # True between a successful `_ensure_sandbox_workflow_started` and
        # the next `PARENT_COMPLETED_SIGNAL`. The orchestrator lives for the
        # whole task run and spawns sandboxes lazily: when a follow-up arrives
        # while `_sandbox_alive=False`, we re-bootstrap before forwarding.
        self._sandbox_alive: bool = False
        self._child_steering_protocol_version: int = 0
        self._consecutive_sandbox_replacement_failures: int = 0

        # Activity tracking for CI follow-up timing. `_last_active_time` is
        # set when the sandbox workflow forwards a heartbeat with
        # agent_active=True.
        self._heartbeat_received: bool = False
        self._last_active_time: Optional[datetime] = None
        self._ci_repetitions: int = 0
        self._pr_fingerprint: Optional[str] = None

    # ------------------------------------------------------------------
    # Input parsing
    # ------------------------------------------------------------------

    @property
    def context(self) -> TaskProcessingContext:
        if self._context is None:
            raise RuntimeError("context accessed before being set")
        return self._context

    @classmethod
    def parse_inputs(cls, inputs: list[str]) -> TaskRunManagementInput:
        loaded = json.loads(inputs[0])
        return TaskRunManagementInput(
            run_id=loaded["run_id"],
            create_pr=loaded.get("create_pr", True),
            slack_thread_context=loaded.get("slack_thread_context"),
            posthog_mcp_scopes=loaded.get("posthog_mcp_scopes", "read_only"),
        )

    # ------------------------------------------------------------------
    # External signal API — preserves the contract of ProcessTaskWorkflow so
    # api.py, models.py, slack_interactivity.py, and the multi-turn runner can
    # keep signaling under the same workflow id without changes.
    # ------------------------------------------------------------------

    @workflow.signal
    async def complete_task(self, status: str = "completed", error_message: Optional[str] = None) -> None:
        # External completion request. Stash it; the main loop forwards a
        # complete_task signal to the child, which ends the current sandbox
        # session. The orchestrator keeps running so subsequent follow-ups
        # can re-bootstrap a fresh sandbox.
        self._pending_external_complete = (status, error_message)

    @workflow.signal
    async def send_followup_message(
        self, message: str | None = None, artifact_ids: Optional[list[str]] = None, steer: bool = False
    ) -> None:
        self._queue_external_followup(message, artifact_ids, steer=steer)

    @workflow.signal(name=SEND_STEER_SIGNAL)
    async def send_steer_message(self, message: str | None = None, artifact_ids: Optional[list[str]] = None) -> None:
        self._queue_external_followup(message, artifact_ids, steer=True)

    @workflow.query(name=STEERING_PROTOCOL_QUERY)
    def steering_protocol_version(self) -> int:
        return STEERING_PROTOCOL_VERSION

    def _queue_external_followup(self, message: str | None, artifact_ids: Optional[list[str]], *, steer: bool) -> None:
        self._pending_external_followups.append(
            PendingExternalFollowup(
                message=message,
                artifact_ids=artifact_ids or [],
                source=FOLLOWUP_SOURCE_USER,
                steer=steer,
                sequence=self._next_followup_sequence,
            )
        )
        self._next_followup_sequence += 1

    @workflow.signal
    async def heartbeat(self, agent_active: bool = False) -> None:
        """Public heartbeat signal — kept for backwards compatibility with
        callers that signal the top-level workflow id directly.

        Heartbeats only flow child -> parent: the child's relay activity
        is the authoritative source of "sandbox is active" and resets the
        child's inactivity timer directly. External heartbeats land here
        only to update the orchestrator's own CI-timing state; we don't
        forward them down to the sandbox.
        """
        self._record_heartbeat(agent_active)

    # ------------------------------------------------------------------
    # Child-facing signals — only the child should send these.
    # ------------------------------------------------------------------

    @temporalio.workflow.signal(name=PARENT_ACK_SIGNAL)
    async def on_child_ack(
        self,
        signal_name: str,
        ack_id: str,
        accepted: bool = True,
        detail: Optional[str] = None,
    ) -> None:
        self._child_acks.append(
            ChildAck(
                signal_name=signal_name,
                ack_id=ack_id,
                accepted=accepted,
                detail=detail,
                received_at=workflow.now(),
            )
        )

    @temporalio.workflow.signal(name=PARENT_HEARTBEAT_SIGNAL)
    async def on_child_heartbeat(self, agent_active: bool = False) -> None:
        self._record_heartbeat(agent_active)

    @temporalio.workflow.signal(name=PARENT_COMPLETED_SIGNAL)
    async def on_child_completed(self, payload: ChildCompletionPayload) -> None:
        """Sandbox session completion notification from the child workflow.

        The orchestrator is long-lived (1:1 with the task run) and outlives
        any individual sandbox. This signal marks the end of *one* sandbox
        session — the main loop processes it, resets per-session state, and
        keeps running so the next external follow-up can bootstrap a fresh
        sandbox.
        """
        # Within a single session, duplicate completions (retries, replays)
        # are coalesced — the main loop only acts on the first one it sees
        # before resetting `_child_completion` back to None.
        if self._child_completion is not None:
            return
        self._child_completion = ChildCompletion(
            success=payload.success,
            error=payload.error,
            sandbox_id=payload.sandbox_id,
            timed_out=payload.timed_out,
        )

    def _record_heartbeat(self, agent_active: bool) -> None:
        self._heartbeat_received = True
        if agent_active:
            now = workflow.now()
            # Debounce updates so a torrent of heartbeats doesn't keep
            # restarting the CI timer with millisecond jitter; the timer
            # rounds to whole seconds anyway.
            if self._last_active_time is None or (now - self._last_active_time) >= HEARTBEAT_DEBOUNCE:
                self._last_active_time = now

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------

    @workflow.run
    async def run(self, input: TaskRunManagementInput) -> TaskRunManagementOutput:
        self._run_id = input.run_id
        self._create_pr = input.create_pr
        self._slack_thread_context = input.slack_thread_context
        self._posthog_mcp_scopes = input.posthog_mcp_scopes
        self._sandbox_workflow_id = f"{workflow.info().workflow_id}-sandbox"
        self._ack_before_completion = _ack_before_completion()

        try:
            self._context = await self._get_task_processing_context()

            await self._track_workflow_event(
                "task_management_started",
                {
                    "run_id": input.run_id,
                    "task_id": self.context.task_id,
                    "repository": self.context.repository,
                    "team_id": self.context.team_id,
                },
            )
            await self._post_slack_update()

            # Restore any follow-ups that a prior orchestrator execution
            # re-queued before its own restart. Must run before the initial
            # bootstrap so the first sandbox sees them in order.
            await self._restore_pending_followups()

            await self._ensure_sandbox_workflow_started()

            # Orchestrator runs for the lifetime of the task run — it owns
            # *multiple* sandbox sessions over time and only exits on
            # explicit cancellation or unrecoverable error. CHILD_COMPLETED
            # is per-session, not terminal; we reset per-session state and
            # wait for the next external signal to bootstrap a fresh sandbox.
            while True:
                event = await self._wait_for_event()
                match event:
                    case TaskEvent.CHILD_COMPLETED:
                        await self._on_sandbox_session_completed()
                    case TaskEvent.EXTERNAL_SIGNAL:
                        await self._drain_external_signals()
                    case TaskEvent.CHILD_FORWARDED:
                        await self._drain_child_signals()
                    case TaskEvent.CI_FOLLOW_UP_DUE:
                        await self._maybe_dispatch_ci_follow_up()
                    case TaskEvent.ACK_RETRY_DUE:
                        await self._retry_stale_acks()
                    case _:
                        raise ValueError(f"Unknown TaskEvent: {event}")

        except asyncio.CancelledError:
            await self._track_workflow_event(
                "task_management_cancelled",
                {
                    "run_id": input.run_id,
                    "task_id": self.context.task_id if self._context else None,
                },
            )
            # Best-effort: tell the sandbox workflow to wind down. It runs
            # independently, so the cancellation propagation is through the
            # signal we send, not Temporal's parent-close machinery.
            if self._sandbox_alive:
                await self._signal_child_complete("cancelled", "Workflow cancelled")
            await self._update_task_run_status("cancelled")
            raise

        except Exception as e:
            error_message = truncate_error_message(str(e))
            await self._track_workflow_event(
                "task_management_failed",
                {
                    "run_id": input.run_id,
                    "task_id": self.context.task_id if self._context else None,
                    "error_type": type(e).__name__,
                    "error_message": error_message,
                },
            )
            await self._update_task_run_status("failed", error_message=error_message, error_type=type(e).__name__)
            return TaskRunManagementOutput(
                success=False,
                error=error_message,
                ci_repetitions=self._ci_repetitions,
            )

        finally:
            if self._slack_thread_context and self._context:
                await self._post_slack_update(sandbox_cleaned=not self._sandbox_alive)

    # ------------------------------------------------------------------
    # Event-wait loop
    # ------------------------------------------------------------------

    async def _wait_for_signal(self) -> TaskEvent:
        await workflow.wait_condition(
            lambda: (
                self._pending_external_complete is not None
                or len(self._pending_external_followups) > 0
                or len(self._child_acks) > 0
                or self._heartbeat_received
                or self._child_completion is not None
            )
        )
        # Older histories processed completion first. New executions drain
        # ACKs before resetting the sandbox session so an already-delivered
        # follow-up is not re-queued onto the replacement sandbox.
        if self._child_completion is not None and (not self._ack_before_completion or not self._child_acks):
            return TaskEvent.CHILD_COMPLETED
        # Prefer external signals when both classes are pending — the child
        # signal drain is cheap and rarely time-critical.
        if self._pending_external_complete is not None or self._pending_external_followups:
            return TaskEvent.EXTERNAL_SIGNAL
        return TaskEvent.CHILD_FORWARDED

    async def _wait_for_ci_follow_up(self) -> TaskEvent:
        # Caller guards on _ci_follow_up_enabled(), so we never enter this
        # task once MAX_CI_REPETITIONS is exhausted — the branch just drops
        # out of the wait set on the next iteration.
        if self._last_active_time is None:
            await workflow.sleep(CI_FOLLOW_UP_DELAY.total_seconds())
        else:
            elapsed = workflow.now() - self._last_active_time
            remaining = CI_FOLLOW_UP_DELAY - elapsed
            if remaining.total_seconds() > 0:
                await workflow.sleep(remaining.total_seconds())
        return TaskEvent.CI_FOLLOW_UP_DUE

    async def _wait_for_ack_retry(self) -> TaskEvent:
        # Sleep until the oldest in-flight signal's ACK deadline. Caller
        # guards on `_pending_ack_slots` being non-empty, so `min()` is safe.
        oldest_sent = min(slot.sent_at for slot in self._pending_ack_slots.values())
        deadline = oldest_sent + ACK_TIMEOUT
        now = workflow.now()
        if deadline > now:
            await workflow.sleep((deadline - now).total_seconds())
        return TaskEvent.ACK_RETRY_DUE

    async def _wait_for_event(self) -> TaskEvent:
        possible: list[asyncio.Task[TaskEvent]] = [
            asyncio.create_task(self._wait_for_signal()),
        ]
        if self._ci_follow_up_enabled():
            possible.append(asyncio.create_task(self._wait_for_ci_follow_up()))
        if self._pending_ack_slots:
            possible.append(asyncio.create_task(self._wait_for_ack_retry()))

        done, pending = await workflow.wait(possible, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

        for task in done:
            if task.exception():
                workflow.logger.warning(
                    "task_management_event_wait_failed",
                    run_id=self._run_id,
                    error=str(task.exception()),
                )
                continue
            return task.result()
        raise RuntimeError("No event completed successfully")

    def _ci_follow_up_enabled(self) -> bool:
        if not self._context:
            return False
        return bool(
            self._context.create_pr and self._context.pr_loop_enabled and self._ci_repetitions < MAX_CI_REPETITIONS
        )

    # ------------------------------------------------------------------
    # Draining queues
    # ------------------------------------------------------------------

    async def _drain_external_signals(self) -> None:
        # Lazy re-bootstrap: if a prior sandbox session ended and we now have
        # follow-ups to deliver, spin up a fresh sandbox first. A standalone
        # `complete_task` arriving without follow-ups is dropped — there's
        # nothing meaningful to complete when no sandbox is running.
        if not self._sandbox_alive:
            if self._pending_external_followups:
                await self._wait_before_replacement_sandbox()
                workflow.logger.info(
                    "task_management_rebootstrapping_for_followup",
                    run_id=self._run_id,
                    pending=len(self._pending_external_followups),
                )
                await self._ensure_sandbox_workflow_started()
            elif self._pending_external_complete is not None:
                workflow.logger.info(
                    "task_management_complete_dropped_no_sandbox",
                    run_id=self._run_id,
                )
                self._pending_external_complete = None
                return

        # Forward all pending external follow-ups first; complete_task is
        # terminal and handled last so we don't drop in-flight messages.
        while self._pending_external_followups:
            followup = self._pending_external_followups.pop(0)
            delivered = await self._signal_child_followup(
                message=followup.message,
                artifact_ids=followup.artifact_ids,
                source=followup.source,
                steer=followup.steer,
                sequence=followup.sequence,
            )
            if delivered is False:
                return
        # The persisted queue is the orchestrator's recovery buffer — keep
        # it in sync after every drain so a restart sees an accurate picture
        # rather than re-delivering work we already forwarded.
        await self._persist_pending_followups()

        if self._pending_external_complete is not None:
            status, error_message = self._pending_external_complete
            self._pending_external_complete = None
            await self._signal_child_complete(status, error_message)

    async def _drain_child_signals(self) -> None:
        # ACKs match pending signal slots by ack_id. We log unmatched ACKs at
        # debug — they happen if a slot was already cleared by a timeout, but
        # the work was still done by the child.
        requeued_followups: list[PendingExternalFollowup] = []
        while self._child_acks:
            ack = self._child_acks.pop(0)
            slot = self._pending_ack_slots.pop(ack.ack_id, None)
            if slot is None:
                workflow.logger.debug(
                    "task_management_ack_unmatched",
                    run_id=self._run_id,
                    signal_name=ack.signal_name,
                    ack_id=ack.ack_id,
                )
                continue
            if not ack.accepted and ack.detail == SHUTDOWN_REJECTION_DETAIL:
                # Sandbox tore down before this signal could be processed.
                # Re-queue follow-ups so the next sandbox session picks them
                # up. complete_task rejections are fine to drop — the child
                # is shutting down precisely because it's already completing.
                followup = self._followup_from_shutdown_rejection(slot)
                if followup is not None:
                    requeued_followups.append(followup)
                continue
            if ack.accepted and slot.signal_name in {SEND_FOLLOWUP_SIGNAL, SEND_STEER_SIGNAL}:
                self._consecutive_sandbox_replacement_failures = 0
            workflow.logger.info(
                "task_management_ack_received",
                run_id=self._run_id,
                signal_name=ack.signal_name,
                ack_id=ack.ack_id,
                accepted=ack.accepted,
                latency_ms=int((ack.received_at - slot.sent_at).total_seconds() * 1000),
                detail=ack.detail,
            )
        self._heartbeat_received = False
        for followup in requeued_followups:
            self._insert_external_followup_in_arrival_order(followup)
        if requeued_followups:
            if _patch_enabled(_PATCH_ID_CLEAR_STEER_ON_SANDBOX_BOUNDARY):
                self._clear_pending_steer_intent()
            self._record_sandbox_replacement_failure()
            # Sync the recovery buffer to reflect the re-queue; otherwise an
            # orchestrator restart would forget about the rejected follow-up.
            await self._persist_pending_followups()

    def _followup_from_shutdown_rejection(self, slot: PendingAckSlot) -> PendingExternalFollowup | None:
        if slot.signal_name in {SEND_FOLLOWUP_SIGNAL, SEND_STEER_SIGNAL} and slot.signal_args is not None:
            _ack_id, message, artifact_ids, source, *_legacy = slot.signal_args
            workflow.logger.warning(
                "task_management_followup_requeued_after_shutdown",
                run_id=self._run_id,
                source=source,
            )
            return PendingExternalFollowup(
                message=message,
                artifact_ids=artifact_ids,
                source=source,
                sequence=slot.sequence,
            )
        workflow.logger.info(
            "task_management_shutdown_rejection_ignored",
            run_id=self._run_id,
            signal_name=slot.signal_name,
        )
        return None

    def _insert_external_followup_in_arrival_order(self, followup: PendingExternalFollowup) -> None:
        for index, pending in enumerate(self._pending_external_followups):
            if pending.sequence > followup.sequence:
                self._pending_external_followups.insert(index, followup)
                return
        self._pending_external_followups.append(followup)

    def _clear_pending_steer_intent(self) -> None:
        for followup in self._pending_external_followups:
            followup.steer = False

    def _record_sandbox_replacement_failure(self) -> None:
        if _patch_enabled(_PATCH_ID_BOUNDED_SANDBOX_REPLACEMENT_RECOVERY):
            self._consecutive_sandbox_replacement_failures += 1

    async def _wait_before_replacement_sandbox(self) -> None:
        if not _patch_enabled(_PATCH_ID_BOUNDED_SANDBOX_REPLACEMENT_RECOVERY):
            return
        failures = self._consecutive_sandbox_replacement_failures
        if failures >= MAX_CONSECUTIVE_SANDBOX_REPLACEMENT_FAILURES:
            if not _patch_enabled(_PATCH_ID_PERSIST_REPLACEMENT_BUDGET):
                raise RuntimeError(
                    f"Sandbox replacement failed {failures} consecutive times before acknowledging a follow-up"
                )
            if await self._persist_pending_followups():
                raise RuntimeError(
                    f"Sandbox replacement failed {failures} consecutive times before acknowledging a follow-up"
                )
            workflow.logger.warning(
                "task_management_sandbox_replacement_budget_persist_failed",
                run_id=self._run_id,
                consecutive_failures=failures,
            )
        if failures == 0:
            return
        delay_seconds = min(2 ** (failures - 1), MAX_SANDBOX_REPLACEMENT_BACKOFF_SECONDS)
        workflow.logger.warning(
            "task_management_sandbox_replacement_backoff",
            run_id=self._run_id,
            consecutive_failures=failures,
            delay_seconds=delay_seconds,
        )
        await workflow.sleep(delay_seconds)

    async def _recover_closed_sandbox(self, error: Exception) -> None:
        child_acks_by_id = {ack.ack_id: ack for ack in self._child_acks}
        accepted_followup_ack = False
        requeued = 0
        for ack_id, slot in self._pending_ack_slots.items():
            ack = child_acks_by_id.get(ack_id)
            if ack is not None:
                if ack.accepted:
                    if slot.signal_name in {SEND_FOLLOWUP_SIGNAL, SEND_STEER_SIGNAL}:
                        accepted_followup_ack = True
                    continue
                if ack.detail != SHUTDOWN_REJECTION_DETAIL:
                    continue
            if slot.signal_name not in {SEND_FOLLOWUP_SIGNAL, SEND_STEER_SIGNAL} or slot.signal_args is None:
                continue
            _ack_id, message, artifact_ids, source, *_legacy = slot.signal_args
            self._insert_external_followup_in_arrival_order(
                PendingExternalFollowup(
                    message=message,
                    artifact_ids=artifact_ids,
                    source=source,
                    sequence=slot.sequence,
                )
            )
            requeued += 1

        if accepted_followup_ack and _patch_enabled(_PATCH_ID_ACCEPTED_ACK_RESETS_REPLACEMENT_BUDGET):
            self._consecutive_sandbox_replacement_failures = 0
        self._clear_pending_steer_intent()
        if requeued:
            self._record_sandbox_replacement_failure()
        workflow.logger.warning(
            "task_management_closed_sandbox_recovered",
            run_id=self._run_id,
            requeued=requeued,
            error=str(error),
        )
        self._pending_ack_slots.clear()
        self._child_acks.clear()
        self._child_completion = None
        self._sandbox_alive = False
        self._child_steering_protocol_version = 0
        self._ci_repetitions = 0
        self._pr_fingerprint = None
        self._heartbeat_received = False
        self._last_active_time = None
        await self._persist_pending_followups()

    # ------------------------------------------------------------------
    # Sandbox session lifecycle (multiple sessions per orchestrator)
    # ------------------------------------------------------------------

    async def _on_sandbox_session_completed(self) -> None:
        """Handle one sandbox session ending without exiting the orchestrator.

        We re-queue any follow-ups whose ACKs never arrived (the work may or
        may not have been delivered — we can't know, so we prefer over- to
        under-delivery), drop ack slots that aren't retryable, reset per-
        session state, and persist the re-queued follow-ups so they survive
        an orchestrator restart.
        """
        completion = self._child_completion
        assert completion is not None
        workflow.logger.info(
            "task_management_sandbox_session_ended",
            run_id=self._run_id,
            success=completion.success,
            sandbox_id=completion.sandbox_id,
            timed_out=completion.timed_out,
            error=completion.error,
        )

        # Best-effort re-queue: any followup slot still awaiting an ACK at
        # session end might or might not have been delivered. We re-queue
        # for the next session — accept potential double-delivery rather
        # than silently dropping user input.
        requeued = 0
        for slot in list(self._pending_ack_slots.values()):
            if slot.signal_name in {SEND_FOLLOWUP_SIGNAL, SEND_STEER_SIGNAL} and slot.signal_args is not None:
                _ack_id, message, artifact_ids, source, *_legacy = slot.signal_args
                self._insert_external_followup_in_arrival_order(
                    PendingExternalFollowup(
                        message=message,
                        artifact_ids=artifact_ids,
                        source=source,
                        sequence=slot.sequence,
                    )
                )
                requeued += 1
        if requeued:
            workflow.logger.warning(
                "task_management_unacked_followups_requeued",
                run_id=self._run_id,
                count=requeued,
            )
            self._record_sandbox_replacement_failure()

        if _patch_enabled(_PATCH_ID_CLEAR_STEER_ON_SANDBOX_BOUNDARY):
            self._clear_pending_steer_intent()

        # Hard-reset per-session state. The next session starts clean —
        # CI counters, fingerprint, heartbeat all belong to the previous
        # sandbox's agent activity, not the new one's.
        self._pending_ack_slots.clear()
        self._child_completion = None
        self._sandbox_alive = False
        self._child_steering_protocol_version = 0
        self._ci_repetitions = 0
        self._pr_fingerprint = None
        self._heartbeat_received = False
        self._last_active_time = None

        # Persist after re-queue so a restart sees the survivors.
        await self._persist_pending_followups()

    async def _restore_pending_followups(self) -> None:
        """Seed `_pending_external_followups` from `TaskRun.state` on startup."""
        assert self._run_id is not None
        try:
            result = await workflow.execute_activity(
                read_pending_followups,
                ReadPendingFollowupsInput(run_id=self._run_id),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except Exception as e:
            workflow.logger.warning(
                "task_management_restore_pending_failed",
                run_id=self._run_id,
                error=str(e),
            )
            return
        if not result.followups:
            return
        for item in result.followups:
            sequence = item.get("sequence")
            if not isinstance(sequence, int):
                sequence = self._next_followup_sequence
            self._next_followup_sequence = max(self._next_followup_sequence, sequence + 1)
            self._pending_external_followups.append(
                PendingExternalFollowup(
                    message=item.get("message"),
                    artifact_ids=list(item.get("artifact_ids") or []),
                    source=item.get("source", FOLLOWUP_SOURCE_USER),
                    steer=item.get("steer") is True,
                    sequence=sequence,
                )
            )
        # Seed the persistence snapshot so the next `_persist_pending_followups`
        # call detects state-vs-DB equality and skips a redundant write.
        self._last_persisted_followups = [asdict(f) for f in self._pending_external_followups]
        workflow.logger.info(
            "task_management_restored_pending_followups",
            run_id=self._run_id,
            count=len(result.followups),
        )

    async def _persist_pending_followups(self) -> bool:
        """Mirror the in-memory queue into `TaskRun.state`.

        Best-effort: failure here doesn't compromise the current execution,
        only the recovery picture if we later restart. Logged so we notice
        sustained failures. Skips the activity when the payload hasn't
        changed since the last write — drain paths fire this every iteration
        and an empty-to-empty no-op would still take a row lock.
        """
        if self._run_id is None:
            return False
        payload = [asdict(f) for f in self._pending_external_followups]
        if payload == self._last_persisted_followups:
            return True
        try:
            await workflow.execute_activity(
                persist_pending_followups,
                PersistPendingFollowupsInput(run_id=self._run_id, followups=payload),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            self._last_persisted_followups = payload
            return True
        except Exception as e:
            workflow.logger.warning(
                "task_management_persist_pending_failed",
                run_id=self._run_id,
                error=str(e),
            )
            return False

    # ------------------------------------------------------------------
    # Sandbox workflow management
    # ------------------------------------------------------------------

    async def _ensure_sandbox_workflow_started(self) -> None:
        """Signal-With-Start the sandbox workflow.

        Idempotent: if the sandbox workflow is already running under
        `_sandbox_workflow_id` (e.g. this orchestrator just restarted while
        the sandbox kept going), Temporal just delivers the bootstrap signal.
        Otherwise it starts a fresh workflow with the input below and the
        bootstrap signal pre-queued.
        """
        assert self._sandbox_workflow_id is not None
        parent_workflow_id = workflow.info().workflow_id
        ack_id = self._new_ack_id()
        self._pending_ack_slots[ack_id] = PendingAckSlot(
            signal_name=PARENT_ATTACHED_SIGNAL,
            sent_at=workflow.now(),
        )
        protocol_version = await workflow.execute_activity(
            ensure_execute_sandbox_started,
            EnsureExecuteSandboxStartedInput(
                workflow_id=self._sandbox_workflow_id,
                workflow_input=ExecuteSandboxInput(
                    run_id=self.context.run_id,
                    parent_workflow_id=parent_workflow_id,
                    create_pr=self._create_pr,
                    slack_thread_context=self._slack_thread_context,
                    posthog_mcp_scopes=self._posthog_mcp_scopes,
                ),
                bootstrap_ack_id=ack_id,
            ),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        self._child_steering_protocol_version = protocol_version if isinstance(protocol_version, int) else 0
        self._sandbox_generation += 1
        # The startup patch is memoized for the workflow lifetime. A distinct
        # marker per sandbox lets an old replay keep its recorded ordering,
        # then adopt ACK-first handling when a later sandbox starts live.
        self._ack_before_completion = self._ack_before_completion or _ack_before_completion_for_sandbox_generation(
            self._sandbox_generation
        )
        # Activity success means Signal-With-Start landed — either delivered
        # to an already-running execution or kicked off a fresh one. Either
        # way, a sandbox session is now in-flight.
        self._sandbox_alive = True

    def _sandbox_handle(self) -> workflow.ExternalWorkflowHandle:
        assert self._sandbox_workflow_id is not None
        return workflow.get_external_workflow_handle(self._sandbox_workflow_id)

    async def _signal_child_followup(
        self,
        message: str | None,
        artifact_ids: list[str],
        source: str = FOLLOWUP_SOURCE_USER,
        steer: bool = False,
        sequence: int | None = None,
    ) -> bool | None:
        if self._sandbox_workflow_id is None:
            workflow.logger.warning(
                "task_management_followup_dropped_no_sandbox",
                run_id=self._run_id,
                source=source,
            )
            return
        ack_id = self._new_ack_id()
        if sequence is None:
            sequence = self._next_followup_sequence
            self._next_followup_sequence += 1
        signal_args: list[Any] = [ack_id, message, artifact_ids, source]
        supports_steering = self._child_steering_protocol_version >= STEERING_PROTOCOL_VERSION
        if steer and workflow.patched(_PATCH_ID_CAPABILITY_GATED_STEERING):
            signal_name = SEND_STEER_SIGNAL if supports_steering else SEND_FOLLOWUP_SIGNAL
        else:
            signal_name = SEND_STEER_SIGNAL if steer else SEND_FOLLOWUP_SIGNAL
        # Register the slot *before* sending so an in-flight send-failure
        # leaves the slot intact for the retry loop to re-attempt. The child
        # dedupes by ack_id so re-sending is safe.
        self._pending_ack_slots[ack_id] = PendingAckSlot(
            signal_name=signal_name,
            sent_at=workflow.now(),
            detail=f"source={source}",
            signal_args=signal_args,
            sequence=sequence,
        )
        try:
            await self._sandbox_handle().signal(signal_name, args=signal_args)
        except Exception as e:
            if _child_cannot_receive_signals(e) and _patch_enabled(_PATCH_ID_CLOSED_CHILD_FOLLOWUP_RECOVERY):
                await self._recover_closed_sandbox(e)
                return False
            # Keep the slot — `_retry_stale_acks` will try again after
            # ACK_TIMEOUT. This is the "child is dead, parent retries"
            # branch the design relies on.
            workflow.logger.warning(
                "task_management_signal_followup_failed",
                run_id=self._run_id,
                source=source,
                error=str(e),
            )
        return True

    async def _signal_child_complete(self, status: str, error_message: Optional[str]) -> None:
        if self._sandbox_workflow_id is None or not self._sandbox_alive:
            # Nothing to tell — the sandbox is already gone (or never started).
            # The orchestrator-level cancellation path still updates TaskRun
            # status separately, so there's no other action needed here.
            return
        ack_id = self._new_ack_id()
        signal_args: list[Any] = [ack_id, status, error_message]
        self._pending_ack_slots[ack_id] = PendingAckSlot(
            signal_name=COMPLETE_TASK_SIGNAL,
            sent_at=workflow.now(),
            signal_args=signal_args,
        )
        try:
            await self._sandbox_handle().signal(COMPLETE_TASK_SIGNAL, args=signal_args)
        except Exception as e:
            if _child_cannot_receive_signals(e) and _patch_enabled(_PATCH_ID_CLOSED_CHILD_COMPLETION_RECOVERY):
                await self._recover_closed_sandbox(e)
                return
            workflow.logger.warning(
                "task_management_signal_complete_failed",
                run_id=self._run_id,
                error=str(e),
            )

    async def _retry_stale_acks(self) -> None:
        """Re-send signals whose ACK hasn't come back within ACK_TIMEOUT.

        The child idempotently re-acks already-processed signals (via its
        own `_acked_ids` set), so a spurious retry costs one extra round-trip
        but never doubles a follow-up. Slots without `signal_args` (the
        bootstrap signal) are dropped after timeout — `ensure_execute_sandbox_started`
        is already activity-level retried, so a missing bootstrap ACK
        means the workflow accepted the signal but its ACK got lost.
        """
        now = workflow.now()
        stale_ids = [ack_id for ack_id, slot in self._pending_ack_slots.items() if (now - slot.sent_at) >= ACK_TIMEOUT]
        for ack_id in stale_ids:
            slot = self._pending_ack_slots[ack_id]
            if slot.retry_count >= MAX_ACK_RETRIES:
                workflow.logger.warning(
                    "task_management_ack_retry_exhausted",
                    run_id=self._run_id,
                    ack_id=ack_id,
                    signal_name=slot.signal_name,
                )
                self._pending_ack_slots.pop(ack_id, None)
                continue
            if slot.signal_args is None:
                workflow.logger.warning(
                    "task_management_ack_retry_skipped_no_args",
                    run_id=self._run_id,
                    ack_id=ack_id,
                    signal_name=slot.signal_name,
                )
                self._pending_ack_slots.pop(ack_id, None)
                continue
            try:
                await self._sandbox_handle().signal(slot.signal_name, args=slot.signal_args)
                slot.sent_at = now
                slot.retry_count += 1
                workflow.logger.info(
                    "task_management_ack_retry",
                    run_id=self._run_id,
                    ack_id=ack_id,
                    signal_name=slot.signal_name,
                    retry_count=slot.retry_count,
                )
            except Exception as e:
                if _child_cannot_receive_signals(e) and _patch_enabled(_PATCH_ID_CLOSED_CHILD_ACK_RETRY_RECOVERY):
                    await self._recover_closed_sandbox(e)
                    return
                # Don't advance sent_at on failure — we want to retry again
                # at the next deadline rather than push it out by ACK_TIMEOUT.
                workflow.logger.warning(
                    "task_management_ack_retry_failed",
                    run_id=self._run_id,
                    ack_id=ack_id,
                    signal_name=slot.signal_name,
                    error=str(e),
                )

    def _new_ack_id(self) -> str:
        # `workflow.uuid4()` is deterministic for replay.
        return str(workflow.uuid4())

    # ------------------------------------------------------------------
    # CI follow-up decision
    # ------------------------------------------------------------------

    async def _maybe_dispatch_ci_follow_up(self) -> None:
        decision = await self._should_run_ci_follow_up()
        match decision:
            case CIFollowUpDecision.FIRE:
                await self._dispatch_ci_follow_up()
            case CIFollowUpDecision.NO_PR:
                # No PR will ever appear — stop the CI loop entirely so the
                # CI timer branch drops out of the wait set.
                self._ci_repetitions = MAX_CI_REPETITIONS
                workflow.logger.info(
                    "task_management_ci_loop_stopped_no_pr",
                    run_id=self._run_id,
                )
            case CIFollowUpDecision.SKIP:
                # Bound the next get_pr_context call to +CI_FOLLOW_UP_DELAY.
                # Mirrors process_task: without this, the next iteration
                # returns immediately whenever last_active_time is older than
                # the delay and the workflow tight-loops GET /repos/.../pulls.
                self._last_active_time = workflow.now()
            case _:
                raise ValueError(f"Unknown CIFollowUpDecision: {decision}")

    async def _should_run_ci_follow_up(self) -> CIFollowUpDecision:
        pr_context = await workflow.execute_activity(
            get_pr_context,
            GetPrContextInput(context=self.context),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if not pr_context:
            return CIFollowUpDecision.NO_PR
        if pr_context.pr_state in ("closed", "merged"):
            workflow.logger.info(
                "task_management_ci_skipped_pr_closed",
                run_id=self._run_id,
                pr_url=pr_context.pr_url,
            )
            return CIFollowUpDecision.SKIP
        if self._pr_fingerprint != pr_context.fingerprint:
            self._pr_fingerprint = pr_context.fingerprint
            workflow.logger.info(
                "task_management_ci_fire",
                run_id=self._run_id,
                pr_url=pr_context.pr_url,
                repetitions=self._ci_repetitions,
            )
            return CIFollowUpDecision.FIRE
        workflow.logger.info(
            "task_management_ci_skipped_pr_unchanged",
            run_id=self._run_id,
            pr_url=pr_context.pr_url,
        )
        return CIFollowUpDecision.SKIP

    async def _dispatch_ci_follow_up(self) -> None:
        self._ci_repetitions += 1
        ci_message = (self._context.ci_prompt if self._context else None) or DEFAULT_CI_MESSAGE
        self._last_active_time = workflow.now()
        await self._signal_child_followup(message=ci_message, artifact_ids=[], source=FOLLOWUP_SOURCE_CI)

    # ------------------------------------------------------------------
    # Activities used directly by the parent
    # ------------------------------------------------------------------

    async def _get_task_processing_context(self) -> TaskProcessingContext:
        assert self._run_id is not None
        return await workflow.execute_activity(
            get_task_processing_context,
            GetTaskProcessingContextInput(run_id=self._run_id, create_pr=self._create_pr),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _track_workflow_event(self, event_name: str, properties: dict) -> None:
        if not self._context:
            return
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

    async def _update_task_run_status(
        self,
        status: str,
        error_message: Optional[str] = None,
        error_type: Optional[str] = None,
    ) -> None:
        run_id = self._run_id
        if run_id is None:
            return
        await workflow.execute_activity(
            update_task_run_status,
            UpdateTaskRunStatusInput(
                run_id=run_id,
                status=status,
                error_message=error_message,
                error_type=error_type,
            ),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _post_slack_update(self, sandbox_cleaned: bool = False) -> None:
        if not self._slack_thread_context or not self._context:
            return
        await workflow.execute_activity(
            post_slack_update,
            PostSlackUpdateInput(
                run_id=self.context.run_id,
                slack_thread_context=self._slack_thread_context,
                sandbox_cleaned=sandbox_cleaned,
            ),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
