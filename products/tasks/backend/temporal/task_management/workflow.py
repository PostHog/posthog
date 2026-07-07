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

from products.tasks.backend.temporal.constants import (
    ACK_TIMEOUT,
    CI_FOLLOW_UP_DELAY,
    DEFAULT_CI_MESSAGE,
    HEARTBEAT_DEBOUNCE,
    MAX_ACK_RETRIES,
    MAX_CI_REPETITIONS,
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
        # True between a successful `_ensure_sandbox_workflow_started` and
        # the next `PARENT_COMPLETED_SIGNAL`. The orchestrator lives for the
        # whole task run and spawns sandboxes lazily: when a follow-up arrives
        # while `_sandbox_alive=False`, we re-bootstrap before forwarding.
        self._sandbox_alive: bool = False

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
    async def send_followup_message(self, message: str | None = None, artifact_ids: Optional[list[str]] = None) -> None:
        self._pending_external_followups.append(
            PendingExternalFollowup(message=message, artifact_ids=artifact_ids or [], source=FOLLOWUP_SOURCE_USER)
        )

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
            error_message = str(e)[:500]
            await self._track_workflow_event(
                "task_management_failed",
                {
                    "run_id": input.run_id,
                    "task_id": self.context.task_id if self._context else None,
                    "error_type": type(e).__name__,
                    "error_message": error_message,
                },
            )
            await self._update_task_run_status("failed", error_message=error_message)
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
        # Session-completion wins outright — short-circuits any pending work
        # because the current sandbox session is ending. The orchestrator
        # itself keeps running; the next follow-up will re-bootstrap a
        # fresh sandbox.
        if self._child_completion is not None:
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
            await self._signal_child_followup(
                message=followup.message,
                artifact_ids=followup.artifact_ids,
                source=followup.source,
            )
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
        any_requeued = False
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
                if self._handle_shutdown_rejection(slot):
                    any_requeued = True
                continue
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
        if any_requeued:
            # Sync the recovery buffer to reflect the re-queue; otherwise an
            # orchestrator restart would forget about the rejected follow-up.
            await self._persist_pending_followups()

    def _handle_shutdown_rejection(self, slot: PendingAckSlot) -> bool:
        """Re-queue rejected follow-up work. Returns True if anything was re-queued."""
        if slot.signal_name == SEND_FOLLOWUP_SIGNAL and slot.signal_args is not None:
            # signal_args = [ack_id, message, artifact_ids, source]
            _ack_id, message, artifact_ids, source = slot.signal_args
            self._pending_external_followups.insert(
                0,
                PendingExternalFollowup(message=message, artifact_ids=artifact_ids, source=source),
            )
            workflow.logger.warning(
                "task_management_followup_requeued_after_shutdown",
                run_id=self._run_id,
                source=source,
            )
            return True
        workflow.logger.info(
            "task_management_shutdown_rejection_ignored",
            run_id=self._run_id,
            signal_name=slot.signal_name,
        )
        return False

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
            if slot.signal_name == SEND_FOLLOWUP_SIGNAL and slot.signal_args is not None:
                _ack_id, message, artifact_ids, source = slot.signal_args
                self._pending_external_followups.append(
                    PendingExternalFollowup(message=message, artifact_ids=artifact_ids, source=source)
                )
                requeued += 1
        if requeued:
            workflow.logger.warning(
                "task_management_unacked_followups_requeued",
                run_id=self._run_id,
                count=requeued,
            )

        # Hard-reset per-session state. The next session starts clean —
        # CI counters, fingerprint, heartbeat all belong to the previous
        # sandbox's agent activity, not the new one's.
        self._pending_ack_slots.clear()
        self._child_completion = None
        self._sandbox_alive = False
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
            self._pending_external_followups.append(
                PendingExternalFollowup(
                    message=item.get("message"),
                    artifact_ids=list(item.get("artifact_ids") or []),
                    source=item.get("source", FOLLOWUP_SOURCE_USER),
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

    async def _persist_pending_followups(self) -> None:
        """Mirror the in-memory queue into `TaskRun.state`.

        Best-effort: failure here doesn't compromise the current execution,
        only the recovery picture if we later restart. Logged so we notice
        sustained failures. Skips the activity when the payload hasn't
        changed since the last write — drain paths fire this every iteration
        and an empty-to-empty no-op would still take a row lock.
        """
        if self._run_id is None:
            return
        payload = [asdict(f) for f in self._pending_external_followups]
        if payload == self._last_persisted_followups:
            return
        try:
            await workflow.execute_activity(
                persist_pending_followups,
                PersistPendingFollowupsInput(run_id=self._run_id, followups=payload),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            self._last_persisted_followups = payload
        except Exception as e:
            workflow.logger.warning(
                "task_management_persist_pending_failed",
                run_id=self._run_id,
                error=str(e),
            )

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
        await workflow.execute_activity(
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
    ) -> None:
        if self._sandbox_workflow_id is None:
            workflow.logger.warning(
                "task_management_followup_dropped_no_sandbox",
                run_id=self._run_id,
                source=source,
            )
            return
        ack_id = self._new_ack_id()
        signal_args: list[Any] = [ack_id, message, artifact_ids, source]
        # Register the slot *before* sending so an in-flight send-failure
        # leaves the slot intact for the retry loop to re-attempt. The child
        # dedupes by ack_id so re-sending is safe.
        self._pending_ack_slots[ack_id] = PendingAckSlot(
            signal_name=SEND_FOLLOWUP_SIGNAL,
            sent_at=workflow.now(),
            detail=f"source={source}",
            signal_args=signal_args,
        )
        try:
            await self._sandbox_handle().signal(SEND_FOLLOWUP_SIGNAL, args=signal_args)
        except Exception as e:
            # Keep the slot — `_retry_stale_acks` will try again after
            # ACK_TIMEOUT. This is the "child is dead, parent retries"
            # branch the design relies on.
            workflow.logger.warning(
                "task_management_signal_followup_failed",
                run_id=self._run_id,
                source=source,
                error=str(e),
            )

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
