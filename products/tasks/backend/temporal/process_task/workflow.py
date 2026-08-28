import json
import asyncio
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Optional

from django.conf import settings

import temporalio
import temporalio.exceptions
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.workflow import ParentClosePolicy

from posthog.dataclasses import frozen
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.oauth import PosthogMcpScopes

from products.tasks.backend.constants import DEV_STACK_IMAGE_NAME, SNAPSHOT_KIND_FILESYSTEM, is_same_run_resume_state
from products.tasks.backend.error_telemetry import truncate_error_message
from products.tasks.backend.logic.services.sandbox import is_public_sandbox_repo
from products.tasks.backend.temporal.babysit_pr.prompts import (
    MAX_RENDERED_COMMENTS,
    MAX_RENDERED_THREADS,
    build_wake_prompt,
)
from products.tasks.backend.temporal.babysit_pr.snapshot import AttentionSet, BabysitJournal, PRSnapshot
from products.tasks.backend.temporal.create_snapshot.workflow import CreateSnapshotForRepositoryInput
from products.tasks.backend.temporal.metrics import increment_pr_babysit_decision
from products.tasks.backend.temporal.patches import ci_follow_up_actionable_gate
from products.tasks.backend.temporal.process_task.activities.get_pr_babysit_snapshot import (
    GetPrBabysitSnapshotInput,
    get_pr_babysit_snapshot,
)
from products.tasks.backend.temporal.process_task.activities.get_pr_context import (
    GetPrContextInput,
    get_pr_context,
    is_pr_actionable,
)

from .activities.cleanup_sandbox import (
    CleanupSandboxInput,
    CompleteRunStreamInput,
    cleanup_sandbox,
    complete_run_stream,
)
from .activities.create_resume_snapshot import (
    CreateResumeSnapshotInput,
    CreateResumeSnapshotOutput,
    create_resume_snapshot,
)
from .activities.emit_progress_activity import EmitProgressInput, emit_progress_activity
from .activities.enforce_self_driving_quota import (
    SELF_DRIVING_QUOTA_CANCELLED,
    SELF_DRIVING_QUOTA_STOP_CHECKING,
    EnforceSelfDrivingRunQuotaInput,
    enforce_self_driving_run_quota,
)
from .activities.execute_task_in_sandbox import ExecuteTaskOutput
from .activities.feature_flags import (
    IsSlackAppAgentDesignEnabledForTaskActivityInput,
    is_slack_app_agent_design_enabled_for_task_activity,
)
from .activities.forward_pending_message import forward_pending_user_message
from .activities.get_sandbox_for_repository import GetSandboxForRepositoryOutput
from .activities.get_task_processing_context import (
    GetTaskProcessingContextInput,
    TaskProcessingContext,
    get_task_processing_context,
)
from .activities.materialize_context_layer import MaterializeContextLayerInput, materialize_context_layer_in_sandbox
from .activities.post_slack_update import PostSlackUpdateInput, post_slack_update
from .activities.provision_sandbox import (
    CheckoutBranchInSandboxInput,
    CloneRepositoryInSandboxInput,
    CloneRepositoryInSandboxOutput,
    CreateSandboxForRepositoryInput,
    CreateSandboxForRepositoryOutput,
    InjectFreshTokensOnResumeInput,
    InvalidateResumeSnapshotInput,
    PrepareSandboxForRepositoryInput,
    PrepareSandboxForRepositoryOutput,
    RestoreSandboxConnectionStateInput,
    checkout_branch_in_sandbox,
    clone_repository_in_sandbox,
    create_sandbox_for_repository,
    get_fresh_image_source_for_context,
    inject_fresh_tokens_on_resume,
    invalidate_resume_snapshot,
    prepare_sandbox_for_repository,
    restore_sandbox_connection_state,
)
from .activities.read_sandbox_logs import ReadSandboxLogsInput, read_sandbox_logs
from .activities.record_peer_message_outcome import (
    RecordPeerMessageOutcomeInput,
    is_timeout_activity_failure,
    peer_message_id_from_context,
    record_peer_message_outcome,
)
from .activities.relay_sandbox_events import (
    RelaySandboxEventsInput,
    relay_sandbox_events,
    relay_sandbox_events_deferred_completion,
)
from .activities.run_wizard import RunWizardInput, run_wizard
from .activities.send_followup_to_sandbox import (
    SEND_FOLLOWUP_MAX_ATTEMPTS,
    STEER_DECLINED_OUTCOME,
    SendFollowupToSandboxInput,
    send_followup_to_sandbox,
)
from .activities.send_permission_response_to_sandbox import (
    PostPermissionDeliveryFailureInput,
    SendPermissionDenialGuidanceInput,
    SendPermissionResponseToSandboxInput,
    post_permission_delivery_failure_notice,
    send_permission_denial_guidance,
    send_permission_response_to_sandbox,
)
from .activities.slack_agent_design_signals import RelayAgentDesignSignalsInput, relay_agent_design_signals
from .activities.start_agent_server import (
    MarkRepoReadyInput,
    StartAgentServerInput,
    StartAgentServerOutput,
    await_agent_server_ready,
    launch_agent_server,
    mark_repo_ready,
    start_agent_server,
)
from .activities.start_dev_stack_preview import (
    StartDevStackPreviewInput,
    WaitDevStackPreviewInput,
    start_dev_stack_preview,
    wait_dev_stack_preview,
)
from .activities.track_workflow_event import SANDBOX_DEADLINE_EVENT, TrackWorkflowEventInput, track_workflow_event
from .activities.update_task_run_status import (
    SANDBOX_GONE_STATE_KEY,
    TIMED_OUT_WALL_CLOCK_STATE_KEY,
    UpdateTaskRunStatusInput,
    update_task_run_status,
)
from .credential_refresh import SANDBOX_GONE_ERROR_MESSAGE, CredentialRefreshExitReason, run_credential_refresh_loop
from .slack_agent_design_relay import SlackAgentDesignRelayInput, SlackAgentDesignRelayWorkflow

DEAD_SANDBOX_ERROR_TYPES = ("SandboxNotRunningError", "SandboxNotFoundError")
MAX_ACCEPTED_MESSAGE_IDS = 500
_PATCH_ID_CANCEL_SANDBOX_CREATION_ON_COMPLETION = "tasks-cancel-sandbox-creation-on-completion"
_PATCH_ID_CONTINUE_AFTER_REPOSITORY_CLONE_FAILURE = "tasks-continue-after-repository-clone-failure"


class _TaskCompletedDuringSandboxCreation(Exception):
    pass


def _is_dead_sandbox_failure(error: BaseException) -> bool:
    cause = error.cause if isinstance(error, temporalio.exceptions.ActivityError) else error
    return isinstance(cause, temporalio.exceptions.ApplicationError) and cause.type in DEAD_SANDBOX_ERROR_TYPES


def _failure_error_type(cause: BaseException | None, exc: Exception) -> str:
    cause_type = getattr(cause, "type", None)
    if isinstance(cause_type, temporalio.exceptions.TimeoutType):
        return cause_type.name.lower()
    if isinstance(cause_type, str) and cause_type:
        return cause_type
    return type(exc).__name__


def _message_dedupe_key(
    message_id: str,
    actor_user_id: int | None,
    message_context: dict[str, Any] | None,
) -> str:
    slack_user_id = (message_context or {}).get("actor_slack_user_id")
    actor_slack_user_id = slack_user_id if isinstance(slack_user_id, str) else ""
    return f"{actor_user_id or ''}:{actor_slack_user_id}:{message_id}"


@frozen
class ResumedSandboxState:
    """Loop state carried across continue_as_new to re-attach without re-provisioning."""

    sandbox_id: str
    sandbox_url: str
    connect_token: Optional[str]
    ci_repetitions: int
    jwt_kid: Optional[str] = None
    pr_fingerprint: Optional[str]
    pr_progress_emitted: bool
    first_user_message_received: bool
    is_agent_design_enabled: bool
    last_active_time: Optional[str]  # ISO8601, or None if never active
    # Defaulted so continue_as_new payloads from pre-rollout runs deserialize.
    pr_unresolved_threads: int = 0
    dev_stack_preview_enabled: bool = False
    babysit_journal: BabysitJournal = field(default_factory=BabysitJournal)
    ci_resume_snapshot_created: bool = False
    accepted_message_ids: list[str] = field(default_factory=list)
    # ISO8601 start of the whole continue_as_new chain, so the wall-clock cap is not
    # reset by a continuation. None on payloads written before this field existed.
    chain_started_at: Optional[str] = None
    agent_active: Optional[bool] = None
    end_of_turn_received: Optional[bool] = None
    last_agent_heartbeat_at: Optional[str] = None
    sandbox_ttl_expires_at: Optional[str] = None
    sandbox_ttl_snapshot_taken: bool = False


@frozen
class PreRotationSandbox:
    sandbox_id: str
    sandbox_url: str | None
    connect_token: str | None
    jwt_kid: str | None
    ttl_expires_at: datetime | None = None
    ttl_snapshot_taken: bool = False


@frozen
class SandboxRotation:
    """Outcome of a rotation attempt: the sandbox the run is now on, and the background
    tasks feeding it. ``sandbox_id`` is None when the run stayed where it was.

    ``routing_restored`` is False when a failed rotation could not point the run's persisted
    routing back at the sandbox still serving it, so follow-ups would address the replacement
    that was torn down.
    """

    sandbox_id: str | None = None
    relay_task: Optional["asyncio.Task[None]"] = None
    credential_refresh_task: Optional["asyncio.Task[None]"] = None
    routing_restored: bool = True
    snapshot_saved: bool = False
    reason: str = "none"


@dataclass
class ProcessTaskInput:
    run_id: str
    create_pr: bool = True
    slack_thread_context: Optional[dict[str, Any]] = None
    posthog_mcp_scopes: PosthogMcpScopes = "read_only"
    prewarmed: bool = False
    initial_message: Optional["PendingFollowup"] = None
    # Set only on a continue_as_new continuation, to skip provisioning and re-attach.
    resumed_sandbox: Optional[ResumedSandboxState] = None


@dataclass
class PendingFollowup:
    message: str | None
    artifact_ids: list[str]
    actor_user_id: int | None = None
    message_id: str | None = None
    # Signal context carried verbatim (e.g. actor_slack_user_id for reply
    # tagging); consumers validate the keys they read.
    context: dict[str, Any] = field(default_factory=dict)
    steer: bool = False
    sequence: int = 0


@dataclass
class PendingPermissionResponse:
    request_id: str
    option_id: str
    actor_user_id: int
    actor_slack_user_id: str | None = None
    is_denial: bool = False
    denial_message: str | None = None
    broker_reason: str | None = None


@dataclass
class ProcessTaskOutput:
    success: bool
    task_result: Optional[ExecuteTaskOutput] = None
    error: Optional[str] = None
    sandbox_id: Optional[str] = None


class TaskEvent(StrEnum):
    SIGNAL_RECEIVED = "signal_received"
    TIMEOUT_REACHED = "timeout_reached"
    MAX_DURATION_REACHED = "max_duration_reached"
    CI_FOLLOW_UP = "ci_follow_up"
    SANDBOX_GONE = "sandbox_gone"
    QUOTA_RECHECK = "quota_recheck"
    SANDBOX_TTL_APPROACHING = "sandbox_ttl_approaching"


class CIFollowUpDecision(StrEnum):
    FIRE = "fire"
    SKIP = "skip"
    NO_PR = "no_pr"
    TERMINAL = "terminal"


@dataclass(frozen=True)
class _BabysitDispatch:
    snapshot: PRSnapshot
    attention: AttentionSet


# Legacy re-exports kept while process_task is still on the worker. New
# workers should import them directly from `products.tasks.backend.temporal.constants`.
from products.tasks.backend.temporal.constants import (  # noqa: E402
    CI_FOLLOW_UP_DELAY,
    DEFAULT_CI_MESSAGE,
    INACTIVITY_TIMEOUT,
    MAX_CI_REPETITIONS,
    PENDING_MESSAGE_FORWARD_TIMEOUT_SECONDS,
    RELAY_SANDBOX_EVENTS_START_TO_CLOSE_TIMEOUT,
    SANDBOX_TTL_SNAPSHOT_LEAD,
    SEND_STEER_SIGNAL,
    STEERING_PROTOCOL_QUERY,
    STEERING_PROTOCOL_VERSION,
    WARM_IDLE_TIMEOUT,
)

# Rolling-deploy deprecation bundle (TODO slug: tasks-ci-follow-up-pr-context-cleanup)
# ---------------------------------------------------------------------------
# The PR-context guard inserted a new `get_pr_context` activity before the
# existing CI follow-up dispatch. Without versioning, replay of pre-rollout
# histories failed with nondeterminism because those histories scheduled
# `send_followup_to_sandbox` directly at this point in the workflow.
#
# Cleanup follows the standard two-step Temporal patch lifecycle:
#   1. First cleanup PR: replace `workflow.patched(...)` with
#      `workflow.deprecate_patch(...)` and remove the legacy replay-only path.
#   2. Second cleanup PR (after another full drain): delete this helper and
#      `_PATCH_ID_CI_FOLLOW_UP_PR_CONTEXT`.
_PATCH_ID_CI_FOLLOW_UP_PR_CONTEXT = "tasks-ci-follow-up-pr-context"

# The follow-up queue patch swapped the single-slot `_pending_followup` for a
# `_pending_followups` list inside the `send_followup_message` signal handler.
# Calling `workflow.patched(...)` from a signal handler is unsafe: signals can
# land in different workflow-task boundaries across replays (rolling deploys,
# sticky-cache eviction, worker restarts), which leaves the patch marker in
# history with no matching command on replay (TMPRL1100). Switch to
# `deprecate_patch(...)` so the marker is treated as compatible regardless of
# which workflow task records it. Same two-step lifecycle as above.
_PATCH_ID_FOLLOWUP_QUEUE = "tasks-follow-up-message-queue"

# Follow-up delivery waits synchronously for the sandbox turn to finish. Keep
# that delivery in the background so a later steer signal can reach the active
# turn, while ordinary follow-ups remain queued behind it.
_PATCH_ID_CONCURRENT_FOLLOWUP_STEERING = "tasks-concurrent-followup-steering"

# Existing onboarding histories include the setup agent in boot_total_ms, so replay must
# preserve that input while new histories subtract the setup agent's elapsed time.
_PATCH_ID_EXCLUDE_WIZARD_FROM_BOOT_TOTAL = "tasks-exclude-wizard-from-boot-total"

# Multi-repo histories before this patch release the agent only after every clone completes.
# Preserve that command order on replay while new runs can release it after the primary clone.
_PATCH_ID_AGENT_READY_AFTER_PRIMARY_CLONE = "tasks-agent-ready-after-primary-clone"

# Desktop preparation links a large workspace and writes compiled package outputs. Give
# that non-idempotent work one attempt with a budget larger than its inner 10-minute cap.
_DESKTOP_BOOTSTRAP_ACTIVITY_TIMEOUT = timedelta(minutes=20)

_DEV_STACK_PREVIEW_WAIT_TIMEOUT = timedelta(minutes=15)

# #60923 dropped the redundant slack post that ran immediately after sandbox
# provisioning — between `_get_sandbox_for_repository` and the agent-start
# progress emit. Pre-rollout histories scheduled a `post_slack_update` activity
# at that point, so removing it unconditionally broke replay of in-flight
# workflows with TMPRL1100: the next command (`emit_progress_activity`) no
# longer matched the recorded `post_slack_update` event. Gate the removal —
# post-rollout executions skip the call, replays of older histories still
# schedule it. Same two-step cleanup lifecycle as the patches above.
_PATCH_ID_DROP_SLACK_POST_AFTER_PROVISIONING = "tasks-drop-slack-post-after-provisioning"

# Self-driving-origin implementation runs periodically re-check the org's self-driving credits quota and
# cancel themselves before opening the billable PR when the org crossed its limit mid-run. Gates
# the recheck timer + activity commands so pre-rollout histories replay without them.
_PATCH_ID_SELF_DRIVING_QUOTA_KILL = "tasks-self-driving-quota-kill"

# How often a PR-less self-driving run re-checks the quota while waiting on agent activity. Frequent
# enough to catch a limit crossed by a parallel run's PR; each check is one Redis read.
SELF_DRIVING_QUOTA_RECHECK_INTERVAL = timedelta(minutes=5)

_ORIGIN_PRODUCT_SIGNAL_REPORT = "signal_report"

# Gates the new agent-design flag-eval execute_activity site.
# Two-step deprecate-then-delete cleanup lifecycle as above.
_PATCH_ID_SLACK_AGENT_DESIGN_STATUS = "tasks-slack-agent-design-status"

# Gates the refusal to execute local-environment (desktop-driven) runs. Pre-guard
# histories of such runs proceeded into provisioning; the marker keeps their replays
# deterministic. Same two-step cleanup lifecycle as above.
_PATCH_ID_SKIP_LOCAL_ENVIRONMENT_RUNS = "tasks-skip-local-environment-runs"

# Defers stream completion to cleanup without breaking existing histories.
_PATCH_ID_DEFER_RUN_STREAM_COMPLETION = "tasks-defer-run-stream-completion"
_PATCH_ID_COMPLETE_STREAM_AFTER_CLEANUP_FAILURE = "tasks-complete-stream-after-cleanup-failure"

# Gates the run lifecycle bounds: the hard wall-clock timer added to `_wait_for_event`
# (a new Timer command, so replays of pre-rollout histories must not schedule it) and the
# onboarding-origin FAILED terminalizations for the inactivity and sandbox-gone paths.
# Same two-step deprecate-then-delete cleanup lifecycle as the patches above.
_PATCH_ID_RUN_LIFECYCLE_BOUNDS = "tasks-run-lifecycle-bounds"

_PATCH_ID_SNAPSHOT_BEFORE_CI_FOLLOW_UP = "tasks-snapshot-before-ci-follow-up"

# Keeps an interactive run alive when follow-up delivery exhausts retries, releasing
# the message's dedupe key so a retry can land; background runs keep the fail-fast
# terminalization poll_for_turn callers rely on. Same cleanup lifecycle as above.
_PATCH_ID_FOLLOWUP_FAILURE_KEEPS_RUN = "tasks-followup-failure-keeps-run"

_PATCH_ID_DEV_STACK_PREVIEW = "tasks-dev-stack-preview"

# `Task.OriginProduct.ONBOARDING`, mirrored as a literal so workflow code stays free of
# Django model imports.
_ONBOARDING_ORIGIN_PRODUCT = "onboarding"


def _deprecate_ci_follow_up_pr_context_patch() -> None:
    workflow.deprecate_patch(_PATCH_ID_CI_FOLLOW_UP_PR_CONTEXT)


def _defer_run_stream_completion() -> bool:
    if not workflow.in_workflow():
        return True
    return workflow.patched(_PATCH_ID_DEFER_RUN_STREAM_COMPLETION)


def _complete_stream_after_cleanup_failure() -> bool:
    if not workflow.in_workflow():
        return True
    return workflow.patched(_PATCH_ID_COMPLETE_STREAM_AFTER_CLEANUP_FAILURE)


def _run_lifecycle_bounds_enabled() -> bool:
    if not workflow.in_workflow():
        return True
    return workflow.patched(_PATCH_ID_RUN_LIFECYCLE_BOUNDS)


def _dev_stack_preview_enabled() -> bool:
    return workflow.in_workflow() and workflow.patched(_PATCH_ID_DEV_STACK_PREVIEW)


@temporalio.workflow.defn(name="process-task")
class ProcessTaskWorkflow(PostHogWorkflow):
    def __init__(self) -> None:
        self._context: Optional[TaskProcessingContext] = None
        self._slack_thread_context: Optional[dict[str, Any]] = None
        self._posthog_mcp_scopes: PosthogMcpScopes = "read_only"
        self._sandbox_id_for_cleanup: Optional[str] = None
        # Captured once the agent server is up, for handing to a continue_as_new continuation.
        self._sandbox_url: Optional[str] = None
        self._sandbox_connect_token: Optional[str] = None
        self._sandbox_jwt_kid: Optional[str] = None
        self._resume_snapshot_invalidated = False
        self._preview_progress_open: bool = False
        self._task_completed: bool = False
        self._completion_status: str = "completed"
        self._completion_error: Optional[str] = None
        self._completion_error_type: Optional[str] = None
        # State marker recorded with the terminal status (e.g. sandbox_gone), so the
        # reason a run ended stays machine-readable without abusing error_message.
        self._completion_timeout_marker: Optional[str] = None
        self._heartbeat_received: bool = False
        self._client_activity_received: bool = False
        self._agent_active: Optional[bool] = None
        self._end_of_turn_received: Optional[bool] = None
        self._last_agent_heartbeat_at: Optional[datetime] = None
        self._prewarmed: bool = False
        self._first_user_message_received: bool = False
        self._sandbox_gone: bool = False
        self._pending_followup: PendingFollowup | None = None
        self._pending_followups: list[PendingFollowup] = []
        self._next_followup_sequence: int = 0
        self._accepted_message_ids: list[str] = []
        self._accepted_message_id_set: set[str] = set()
        self._active_followup_task: asyncio.Task[None] | None = None
        self._shutting_down: bool = False
        self._pending_permission_responses: list[PendingPermissionResponse] = []
        self._ci_repetitions: int = 0
        self._last_active_time: Optional[datetime] = None
        # Start of the continue_as_new chain, carried across continuations so the
        # wall-clock cap measures the whole chain rather than restarting per run.
        # None on the first execution, where workflow.info().start_time is the anchor.
        self._chain_started_at: Optional[datetime] = None
        # Tracks which progress step is currently in-progress (step, label,
        # group) so we can emit a "failed" transition from the workflow-level
        # exception handler onto the right card.
        self._current_progress_step: Optional[tuple[str, str, str]] = None
        self._pr_fingerprint: Optional[str] = None
        # Last observed unresolved review-thread count. Starting at 0 means
        # feedback posted before the first poll still reads as new.
        self._pr_unresolved_threads: int = 0
        # Emit the "PR opened / keeping CI green" progress once, the first time we observe a PR — the
        # agent opens it mid-run and then keeps it green, so without this the UI dead-ends at "Started agent".
        self._pr_progress_emitted: bool = False
        self._babysit_journal: BabysitJournal = BabysitJournal()
        self._pending_babysit: Optional[_BabysitDispatch] = None
        self._ci_resume_snapshot_created: bool = False
        self._sandbox_ttl_expires_at: Optional[datetime] = None
        self._sandbox_ttl_snapshot_taken: bool = False
        # Decided once at workflow start; gates the placeholder skip + relay spawn.
        self._is_agent_design_enabled: bool = False
        self._dev_stack_preview_enabled: bool = False
        # Deadline-based so heartbeats waking the event loop don't keep resetting the timer.
        self._self_driving_quota_next_check_at: Optional[datetime] = None
        self._self_driving_quota_checks_active: bool = True
        self._current_slack_relay_workflow_id: Optional[str] = None

    @property
    def context(self) -> TaskProcessingContext:
        if self._context is None:
            raise RuntimeError("context accessed before being set")
        return self._context

    @staticmethod
    def _should_skip_followup(message: str | None, artifact_ids: list[str]) -> bool:
        return not message and not artifact_ids

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ProcessTaskInput:
        loaded = json.loads(inputs[0])
        # continue_as_new carries ProcessTaskInput through Temporal's data converter, not this
        # JSON path, but reconstruct resumed_sandbox anyway so a manual re-start keeps it.
        resumed = loaded.get("resumed_sandbox")
        if resumed and isinstance(resumed.get("babysit_journal"), dict):
            # ResumedSandboxState(**resumed) would leave this nested dataclass a plain dict,
            # which later blows up when the babysit poll calls .attention() on it.
            resumed = {**resumed, "babysit_journal": BabysitJournal(**resumed["babysit_journal"])}
        return ProcessTaskInput(
            run_id=loaded["run_id"],
            create_pr=loaded.get("create_pr", True),
            slack_thread_context=loaded.get("slack_thread_context"),
            posthog_mcp_scopes=loaded.get("posthog_mcp_scopes", "read_only"),
            prewarmed=loaded.get("prewarmed", False),
            initial_message=(
                PendingFollowup(**loaded["initial_message"])
                if isinstance(loaded.get("initial_message"), dict)
                else None
            ),
            resumed_sandbox=ResumedSandboxState(**resumed) if resumed else None,
        )

    async def _wait_for_task_external_event(self):
        await workflow.wait_condition(
            lambda: (
                self._task_completed
                or self._sandbox_gone
                or self._heartbeat_received
                or self._client_activity_received
                or self._has_dispatchable_followup()
                or len(self._pending_permission_responses) > 0
            )
        )
        if self._sandbox_gone and not self._task_completed:
            return TaskEvent.SANDBOX_GONE
        return TaskEvent.SIGNAL_RECEIVED

    def _has_dispatchable_followup(self) -> bool:
        if self._active_followup_task is None:
            return self._pending_followup is not None or bool(self._pending_followups)
        if self._active_followup_task.done():
            return True
        return any(followup.steer for followup in self._pending_followups)

    def _pop_next_followup(self, *, steer_only: bool = False) -> PendingFollowup | None:
        if not steer_only and self._pending_followup is not None:
            followup = self._pending_followup
            self._pending_followup = None
            return followup
        for index, followup in enumerate(self._pending_followups):
            if not steer_only or followup.steer:
                return self._pending_followups.pop(index)
        return None

    def _insert_followup_in_arrival_order(self, followup: PendingFollowup) -> None:
        for index, pending in enumerate(self._pending_followups):
            if pending.sequence > followup.sequence:
                self._pending_followups.insert(index, followup)
                return
        self._pending_followups.append(followup)

    async def _dispatch_next_followup(self) -> bool:
        if self._active_followup_task is not None:
            if self._active_followup_task.done():
                task = self._active_followup_task
                self._active_followup_task = None
                await task
                return True
            followup = self._pop_next_followup(steer_only=True)
            if followup is None:
                return False
            await self._dispatch_followup(followup)
            return True

        followup = self._pop_next_followup()
        if followup is None:
            return False
        self._active_followup_task = asyncio.create_task(self._dispatch_followup(followup))
        return True

    async def _dispatch_followup(self, followup: PendingFollowup) -> None:
        self._last_active_time = workflow.now()
        self._first_user_message_received = True
        if self._should_skip_followup(followup.message, followup.artifact_ids):
            workflow.logger.warning(
                "empty_followup_skipped",
                extra={"run_id": self.context.run_id},
            )
            return
        outcome = await self._send_followup_to_sandbox(
            message=followup.message,
            artifact_ids=followup.artifact_ids,
            actor_user_id=followup.actor_user_id,
            message_id=followup.message_id,
            context=followup.context,
            steer=followup.steer,
        )
        if followup.steer and outcome == STEER_DECLINED_OUTCOME:
            self._insert_followup_in_arrival_order(
                PendingFollowup(
                    message=followup.message,
                    artifact_ids=followup.artifact_ids,
                    actor_user_id=followup.actor_user_id,
                    message_id=followup.message_id,
                    context=followup.context,
                    sequence=followup.sequence,
                ),
            )

    async def _finish_active_followup(self) -> None:
        self._shutting_down = True
        if self._completion_status == "cancelled":
            self._pending_followup = None
            self._pending_followups.clear()
            if self._active_followup_task is not None:
                task = self._active_followup_task
                self._active_followup_task = None
                await self._cancel_relay(task)
            return

        while True:
            if self._active_followup_task is not None:
                task = self._active_followup_task
                self._active_followup_task = None
                await task

            if self._pending_followup is None and not self._pending_followups:
                return
            if not workflow.patched(_PATCH_ID_CONCURRENT_FOLLOWUP_STEERING):
                return

            followup = self._pop_next_followup()
            if followup is not None:
                await self._dispatch_followup(followup)

    async def _wait_for_inactivity(self, timeout: timedelta = INACTIVITY_TIMEOUT):
        await workflow.sleep(timeout.total_seconds())
        return TaskEvent.TIMEOUT_REACHED

    async def _wait_for_max_run_duration(self, cap: timedelta):
        """Hard wall-clock cap, measured from the chain start and never reset by heartbeats.

        The inactivity timer restarts on every heartbeat, so a wedged-but-heartbeating
        agent never trips it; this ceiling catches that case. The anchor comes from
        `_chain_start_time`, which survives continue_as_new; both it and
        `workflow.info().start_time` are deterministic across replays, so recomputing the
        remaining time on each loop iteration is replay-safe.
        """
        elapsed = workflow.now() - self._chain_start_time()
        remaining = (cap - elapsed).total_seconds()
        if remaining > 0:
            await workflow.sleep(remaining)
        return TaskEvent.MAX_DURATION_REACHED

    async def _wait_for_ci_follow_up(self):
        if self._last_active_time:
            elapsed = workflow.now() - self._last_active_time
            remaining = CI_FOLLOW_UP_DELAY - elapsed
            if remaining.total_seconds() > 0:
                workflow.logger.info(
                    "Waiting for CI follow-up event",
                    extra={
                        "run_id": self.context.run_id,
                        "repetitions": self._ci_repetitions,
                        "delay_seconds": remaining.total_seconds(),
                    },
                )
                await workflow.sleep(remaining.total_seconds())
        else:
            await workflow.sleep(CI_FOLLOW_UP_DELAY.total_seconds())
        return TaskEvent.CI_FOLLOW_UP

    def _self_driving_quota_recheck_scheduled(self) -> bool:
        return (
            self._self_driving_quota_checks_active
            and self._context is not None
            and self.context.origin_product == _ORIGIN_PRODUCT_SIGNAL_REPORT
            # Research / repo-selection / custom-agent sessions run with create_pr=False and can
            # never open the billable PR; rechecking them would let the quota gate cancel
            # in-flight research.
            and self.context.create_pr
            and workflow.patched(_PATCH_ID_SELF_DRIVING_QUOTA_KILL)
        )

    def _record_sandbox_deadline(self, created: CreateSandboxForRepositoryOutput) -> None:
        """Remember when the provider will kill this sandbox, so the run can snapshot first.

        A fresh sandbox is a fresh clock, so the previous one's snapshot state does not carry
        over. Histories recorded before the activity reported a deadline decode ``None`` here,
        which leaves the timer unscheduled and keeps their replays command-for-command
        identical.
        """
        self._sandbox_ttl_snapshot_taken = False
        self._sandbox_ttl_expires_at = (
            datetime.fromisoformat(created.ttl_expires_at) if created.ttl_expires_at else None
        )
        if self._sandbox_ttl_expires_at is not None:
            workflow.logger.info(
                "sandbox_deadline_recorded",
                extra={
                    "run_id": self.context.run_id,
                    "sandbox_id": created.sandbox_id,
                    "ttl_expires_at": created.ttl_expires_at,
                },
            )

    def _sandbox_deadline_snapshot_scheduled(self) -> bool:
        """Whether a pre-deadline snapshot is still worth waiting for.

        Only interactive runs on resume snapshots: everything else has nothing to restore, so
        the snapshot would cost provider time for a session no one can pick back up.
        """
        return (
            self._sandbox_ttl_expires_at is not None
            and not self._sandbox_ttl_snapshot_taken
            and self._context is not None
            and self._context.mode == "interactive"
            and self._context.use_modal_resume_snapshots
        )

    def _sandbox_rotation_block_reason(self) -> str | None:
        """Why this run may not move onto a replacement sandbox, or None when it may.

        Only while nothing is in flight: rotation restores a filesystem snapshot, so a turn
        underway would be cut off mid-thought with no way to resume it. A delivery that has
        not yet produced an active-state signal counts as in flight too, which is why the
        follow-up task is checked alongside the agent's own state.

        The reason is what tells a rollout whether rotation is idle-gated out of the runs that
        need it most, so it is a metric label rather than a log line.
        """
        if self._context is None or not self._context.sandbox_rotation_enabled:
            return "flag_disabled"
        if self._agent_active:
            return "agent_active"
        if self._active_followup_task is not None and not self._active_followup_task.done():
            return "followup_in_flight"
        if self._task_completed:
            return "run_completed"
        return None

    async def _wait_for_sandbox_deadline(self) -> TaskEvent:
        """Wake up shortly before the provider kills the sandbox.

        Fires immediately when the lead time has already passed, which is the case a
        continuation inherits, so a late-hydrated deadline still gets its snapshot.
        """
        assert self._sandbox_ttl_expires_at is not None
        remaining = (self._sandbox_ttl_expires_at - SANDBOX_TTL_SNAPSHOT_LEAD) - workflow.now()
        if remaining.total_seconds() > 0:
            await workflow.sleep(remaining.total_seconds())
        return TaskEvent.SANDBOX_TTL_APPROACHING

    async def _wait_for_quota_recheck(self):
        if self._self_driving_quota_next_check_at is None:
            self._self_driving_quota_next_check_at = workflow.now() + SELF_DRIVING_QUOTA_RECHECK_INTERVAL
        remaining = self._self_driving_quota_next_check_at - workflow.now()
        if remaining.total_seconds() > 0:
            await workflow.sleep(remaining.total_seconds())
        return TaskEvent.QUOTA_RECHECK

    def _describe_wait(self, *, warm_idle: bool, ci_follow_up_scheduled: bool, inactivity_timeout: timedelta) -> str:
        """Human-readable summary of what the loop is blocked on, for the Temporal UI.

        The loop blocks on bare `workflow.sleep` timers (CI follow-up, inactivity), which render
        as unlabeled Timer events — indistinguishable from a hang at a glance. This names the wait.
        """
        if warm_idle:
            return "⏳ Warm sandbox idle — waiting for the first user message."

        timeout_min = max(1, round(inactivity_timeout.total_seconds() / 60))
        if not ci_follow_up_scheduled:
            return f"⏳ Waiting for the agent to finish or send an update (inactivity timeout {timeout_min}m)."

        next_check = CI_FOLLOW_UP_DELAY
        if self._last_active_time:
            remaining = CI_FOLLOW_UP_DELAY - (workflow.now() - self._last_active_time)
            if remaining > timedelta(0):
                next_check = remaining
        next_min = max(1, round(next_check.total_seconds() / 60))
        return (
            f"⏳ Waiting for the agent, or to re-check the PR's CI in ~{next_min}m "
            f"(CI follow-up {self._ci_repetitions + 1}/{MAX_CI_REPETITIONS}; inactivity timeout {timeout_min}m)."
        )

    async def _wait_for_event(self) -> TaskEvent:
        warm_idle = self._prewarmed and not self._first_user_message_received

        ci_follow_up_scheduled = (
            not warm_idle
            and self._context is not None
            and self._context.create_pr
            and self._context.pr_loop_enabled
            and self._ci_repetitions < MAX_CI_REPETITIONS
        )
        # When CI follow-up is scheduled, the inactivity timer must outlive
        # CI_FOLLOW_UP_DELAY. The testing-only `TASKS_INACTIVITY_TIMEOUT_SECONDS`
        # env var bypasses the floor, but only when explicitly set AND short —
        # so a misconfigured large value still respects the CI floor.
        base_timeout = self.context.inactivity_timeout()
        ci_follow_up_floor = CI_FOLLOW_UP_DELAY + timedelta(minutes=1)
        testing_override_active = bool(settings.TASKS_INACTIVITY_TIMEOUT_SECONDS) and (
            base_timeout < ci_follow_up_floor
        )
        if warm_idle:
            inactivity_timeout = min(WARM_IDLE_TIMEOUT, base_timeout)
        elif ci_follow_up_scheduled and not testing_override_active:
            inactivity_timeout = max(base_timeout, ci_follow_up_floor)
        else:
            inactivity_timeout = base_timeout

        workflow.set_current_details(
            self._describe_wait(
                warm_idle=warm_idle,
                ci_follow_up_scheduled=ci_follow_up_scheduled,
                inactivity_timeout=inactivity_timeout,
            )
        )

        possible_events: list[asyncio.Task[TaskEvent]] = [
            asyncio.create_task(self._wait_for_task_external_event()),
            asyncio.create_task(self._wait_for_inactivity(inactivity_timeout)),
        ]
        # Hard wall-clock cap, independent of the heartbeat-reset inactivity timer. The
        # patch gate keeps replays of pre-rollout histories from scheduling the new timer;
        # None means the run is exempt (interactive sessions a human may keep open for hours).
        if _run_lifecycle_bounds_enabled():
            max_run_duration = self.context.max_run_duration()
            if max_run_duration is not None:
                possible_events.append(asyncio.create_task(self._wait_for_max_run_duration(max_run_duration)))
        if self._sandbox_deadline_snapshot_scheduled():
            possible_events.append(asyncio.create_task(self._wait_for_sandbox_deadline()))
        if ci_follow_up_scheduled:
            possible_events.append(asyncio.create_task(self._wait_for_ci_follow_up()))
        if not warm_idle and self._self_driving_quota_recheck_scheduled():
            possible_events.append(asyncio.create_task(self._wait_for_quota_recheck()))
        done, pending = await workflow.wait(possible_events, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        pending_tasks_results = await asyncio.gather(
            *pending, return_exceptions=True
        )  # Ensure all pending tasks are cancelled
        for task in done:
            if task.exception():
                workflow.logger.warning(
                    "Event wait task failed",
                    extra={
                        "run_id": self.context.run_id,
                        "error": str(task.exception()),
                    },
                )
                continue
            return task.result()
        for task_result in pending_tasks_results:
            if isinstance(task_result, Exception):
                workflow.logger.warning(
                    "Pending event wait task failed during cancellation",
                    extra={
                        "run_id": self.context.run_id,
                        "error": str(task_result),
                    },
                )
            if isinstance(task_result, TaskEvent):
                workflow.logger.info(
                    "Pending event wait task completed during cancellation",
                    extra={
                        "run_id": self.context.run_id,
                        "event": task_result.value,
                    },
                )
                return task_result
        raise RuntimeError("No event was completed successfully")

    async def _should_run_ci_follow_up(self) -> CIFollowUpDecision:
        """Check whether a CI follow-up message should be sent to the agent.

        Returns "fire" when the PR has changed and the agent should act,
        "skip" when the PR exists but hasn't changed (or is closed), and
        "no_pr" when no PR was created — the caller should stop the CI
        loop entirely in that case.

        This is safe because the CI timer only fires after the agent has
        been idle for the full CI_FOLLOW_UP_DELAY (heartbeats preempt
        and restart the timer). By the time we reach this check, the
        agent has finished working — if no PR exists at this point, one
        won't appear later.
        """
        if self.context.pr_babysit_enabled:
            decision = await self._should_run_babysit_follow_up()
            increment_pr_babysit_decision(decision.value)
            return decision
        pr_context = await workflow.execute_activity(
            get_pr_context,
            GetPrContextInput(context=self.context),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if not pr_context:
            workflow.logger.info(
                "PR context is missing, stopping CI follow-up loop",
                extra={"run_id": self.context.run_id},
            )
            return CIFollowUpDecision.NO_PR
        if pr_context.pr_url and not self._pr_progress_emitted:
            await self._emit_pr_opened_progress(pr_context.pr_url)
        if pr_context.pr_state in ("closed", "merged"):
            workflow.logger.info(
                "PR is closed, skipping CI follow-up",
                extra={
                    "run_id": self.context.run_id,
                    "pr_url": pr_context.pr_url,
                    "pr_state": pr_context.pr_state,
                },
            )
            return CIFollowUpDecision.SKIP
        fingerprint_changed = self._pr_fingerprint != pr_context.fingerprint
        if not ci_follow_up_actionable_gate():
            # Legacy replay path: any fingerprint change fires; feedback is not consulted.
            if not fingerprint_changed:
                return CIFollowUpDecision.SKIP
            self._pr_fingerprint = pr_context.fingerprint
            return CIFollowUpDecision.FIRE
        # New unresolved review threads are feedback for the agent, and comparing
        # against the last-seen count means its own thread replies (which never
        # resolve anything) can't re-trigger it.
        new_feedback = pr_context.unresolved_threads > self._pr_unresolved_threads
        self._pr_unresolved_threads = pr_context.unresolved_threads
        if not fingerprint_changed and not new_feedback:
            workflow.logger.info(
                "PR context has not changed, skipping CI follow-up",
                extra={
                    "run_id": self.context.run_id,
                    "pr_url": pr_context.pr_url,
                    "pr_state": pr_context.pr_state,
                },
            )
            return CIFollowUpDecision.SKIP
        self._pr_fingerprint = pr_context.fingerprint
        fire = (fingerprint_changed and is_pr_actionable(pr_context)) or new_feedback
        workflow.logger.info(
            "PR context has changed, deciding CI follow-up",
            extra={
                "run_id": self.context.run_id,
                "pr_url": pr_context.pr_url,
                "pr_state": pr_context.pr_state,
                "ci_status": pr_context.ci_status,
                "changes_requested": pr_context.changes_requested,
                "unresolved_threads": pr_context.unresolved_threads,
                "new_feedback": new_feedback,
                "fire": fire,
            },
        )
        return CIFollowUpDecision.FIRE if fire else CIFollowUpDecision.SKIP

    async def _emit_pr_opened_progress(self, pr_url: str) -> None:
        # First time we observe a PR: surface "Opened pull request" + "Keeping CI green" so the UI moves
        # past "Started agent". The url rides the "pr" step's detail; the frontend turns it into the CTA.
        self._pr_progress_emitted = True
        await self._emit_progress("pr", "completed", "Opened pull request", "setup", detail=pr_url)
        await self._emit_progress("ci", "in_progress", "Keeping CI green", "setup")

    def _start_dev_stack_preview(self, sandbox_id: str) -> "asyncio.Task[None] | None":
        repository = self.context.repository
        if not repository:
            return None
        return asyncio.ensure_future(self._run_dev_stack_preview(sandbox_id, repository))

    async def _run_dev_stack_preview(self, sandbox_id: str, repository: str) -> None:
        try:
            output = await workflow.execute_activity(
                start_dev_stack_preview,
                StartDevStackPreviewInput(
                    context=self.context,
                    sandbox_id=sandbox_id,
                    repository=repository,
                ),
                start_to_close_timeout=timedelta(minutes=3),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except Exception:
            workflow.logger.warning(
                "Could not start the dev stack preview",
                extra={"run_id": self.context.run_id, "sandbox_id": sandbox_id},
            )
            await self._emit_progress("preview", "failed", "Preview didn't start", "setup")
            return
        if not output.started:
            return
        self._preview_progress_open = True
        try:
            await workflow.execute_activity(
                wait_dev_stack_preview,
                WaitDevStackPreviewInput(context=self.context, sandbox_id=sandbox_id),
                start_to_close_timeout=_DEV_STACK_PREVIEW_WAIT_TIMEOUT,
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except Exception:
            workflow.logger.warning(
                "Gave up waiting for the dev stack preview",
                extra={"run_id": self.context.run_id, "sandbox_id": sandbox_id},
            )
        self._preview_progress_open = False

    async def _close_dev_stack_preview_progress(self) -> None:
        if not self._preview_progress_open:
            return
        self._preview_progress_open = False
        await self._emit_progress("preview", "failed", "Preview didn't start", "setup")

    async def _should_run_babysit_follow_up(self) -> CIFollowUpDecision:
        self._pending_babysit = None
        snapshot = await workflow.execute_activity(
            get_pr_babysit_snapshot,
            GetPrBabysitSnapshotInput(context=self.context),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if not snapshot:
            workflow.logger.info(
                "PR context is missing, stopping CI follow-up loop",
                extra={"run_id": self.context.run_id},
            )
            return CIFollowUpDecision.NO_PR
        if snapshot.pr_url and not self._pr_progress_emitted:
            await self._emit_pr_opened_progress(snapshot.pr_url)
        if snapshot.is_terminal:
            workflow.logger.info(
                "PR reached a terminal state, stopping CI follow-up loop",
                extra={
                    "run_id": self.context.run_id,
                    "pr_url": snapshot.pr_url,
                    "pr_state": snapshot.pr_state,
                },
            )
            label = "PR merged" if snapshot.pr_state == "merged" else "PR closed"
            await self._emit_progress("ci", "completed", label, "setup")
            return CIFollowUpDecision.TERMINAL
        attention = self._babysit_journal.attention(snapshot)
        if attention.is_empty:
            workflow.logger.info(
                "PR has nothing needing attention, skipping CI follow-up",
                extra={
                    "run_id": self.context.run_id,
                    "pr_url": snapshot.pr_url,
                    "pr_state": snapshot.pr_state,
                    "head_sha": snapshot.head_sha,
                },
            )
            return CIFollowUpDecision.SKIP
        self._pending_babysit = _BabysitDispatch(snapshot=snapshot, attention=attention)
        workflow.logger.info(
            "PR needs attention, dispatching CI follow-up",
            extra={
                "run_id": self.context.run_id,
                "pr_url": snapshot.pr_url,
                "pr_state": snapshot.pr_state,
                "head_sha": snapshot.head_sha,
                "failing_checks": len(attention.failing_checks),
                "threads": len(attention.threads),
                "comments": len(attention.comments),
                "conflict": attention.conflict,
            },
        )
        return CIFollowUpDecision.FIRE

    async def _dispatch_ci_follow_up(self) -> None:
        self._ci_repetitions += 1
        pending = self._pending_babysit
        if pending is None:
            ci_message = self.context.ci_prompt or DEFAULT_CI_MESSAGE
        else:
            ci_message = build_wake_prompt(
                pending.snapshot.pr_url,
                pending.attention,
                extra_instructions=self.context.ci_prompt,
            )
        self._last_active_time = workflow.now()
        await self._send_followup_to_sandbox(ci_message, [], user_originated=False)
        if pending is not None:
            # Record only what the prompt rendered; items past the render caps stay unrecorded
            # so a later tick delivers them instead of silently marking them handled.
            dispatched = pending.attention.capped(MAX_RENDERED_THREADS, MAX_RENDERED_COMMENTS)
            self._babysit_journal = self._babysit_journal.record(pending.snapshot, dispatched)
            self._pending_babysit = None

    @workflow.run
    async def run(self, input: ProcessTaskInput) -> ProcessTaskOutput:
        sandbox_id = None
        sandbox_cleaned = False
        run_stream_completed = False
        timeout_event: Optional[TaskEvent] = None
        # Handing the live sandbox to the next execution — the finally must not tear it down.
        continuing_as_new = False
        run_id = input.run_id
        self._sandbox_id_for_cleanup = None
        self._slack_thread_context = input.slack_thread_context
        self._prewarmed = input.prewarmed
        credential_refresh_task: asyncio.Task[None] | None = None
        permission_response_task: asyncio.Task[None] | None = None
        preview_task: asyncio.Task[None] | None = None
        try:
            self._context = await self._get_task_processing_context(input)
            self._posthog_mcp_scopes = input.posthog_mcp_scopes
            # A local-environment run is driven by the user's desktop agent — QUEUED does not
            # mean "awaiting a cloud workflow". Executing it here would boot a sandbox the repo
            # was never cloned into and, once the attempts burn out, stomp the live local
            # session's status. Refuse without touching the run. The environment check comes
            # first so cloud runs (and unit tests exercising them outside a workflow event
            # loop) never call ``workflow.patched``.
            if self.context.environment == "local" and workflow.patched(_PATCH_ID_SKIP_LOCAL_ENVIRONMENT_RUNS):
                workflow.logger.warning(
                    "Refusing to process local-environment run in cloud workflow",
                    extra={"run_id": run_id, "task_id": self.context.task_id},
                )
                return ProcessTaskOutput(
                    success=False,
                    error="Run environment is 'local' (desktop-driven); refusing to execute it as a cloud workflow",
                )
            if input.resumed_sandbox is None:
                self._dev_stack_preview_enabled = self.context.dev_stack_preview_enabled
                sandbox_id, sandbox_url, sandbox_connect_token = await self._provision_and_start_agent(input, run_id)
            else:
                # continue_as_new continuation — re-attach to the running sandbox, skip setup.
                self._restore_resumed_state(input.resumed_sandbox)
                sandbox_id = input.resumed_sandbox.sandbox_id
                self._sandbox_id_for_cleanup = sandbox_id
                sandbox_url = input.resumed_sandbox.sandbox_url
                sandbox_connect_token = input.resumed_sandbox.connect_token
                self._sandbox_jwt_kid = input.resumed_sandbox.jwt_kid
                workflow.logger.info(
                    "process_task_resumed_after_continue_as_new",
                    extra={"run_id": run_id, "sandbox_id": sandbox_id},
                )
            self._sandbox_url = sandbox_url
            self._sandbox_connect_token = sandbox_connect_token

            relay_task: asyncio.Task[None] | None = self._spawn_event_relay(
                sandbox_url, sandbox_connect_token, sandbox_id
            )

            # Delivered concurrently with the main loop: an approval can arrive while
            # the loop is parked inside a followup activity whose turn is blocked on
            # that very approval — delivering inline would livelock until the
            # followup read-times-out.
            permission_response_task = asyncio.ensure_future(self._deliver_pending_permission_responses())

            if self.context.has_github_credentials:
                credential_refresh_task = asyncio.ensure_future(
                    self._run_credential_refresh_until_sandbox_gone(sandbox_id)
                )

            if self._dev_stack_preview_enabled and _dev_stack_preview_enabled():
                preview_task = self._start_dev_stack_preview(sandbox_id)

            # A continuation already delivered the first user message in a prior execution.
            if input.resumed_sandbox is None and input.initial_message is not None:
                self._pending_followups.append(input.initial_message)
                await self._dispatch_next_followup()
            elif input.resumed_sandbox is None and self._should_forward_pending_user_message():
                await self._forward_pending_user_message()

            # Wait for completion signal or inactivity timeout.
            # Heartbeat signals reset the inactivity timer, keeping the workflow alive
            # as long as the agent is actively producing logs.
            while not self._task_completed:
                if self._should_continue_as_new(sandbox_id):
                    assert sandbox_id is not None
                    continuing_as_new = True
                    workflow.logger.info(
                        "process_task_continue_as_new",
                        extra={
                            "run_id": run_id,
                            "sandbox_id": sandbox_id,
                            "history_length": workflow.info().get_current_history_length(),
                        },
                    )
                    # Stop the background loops but leave the sandbox for the next execution.
                    for task in (
                        relay_task,
                        credential_refresh_task,
                        permission_response_task,
                        preview_task,
                    ):
                        if task is not None:
                            await self._cancel_relay(task)
                    workflow.continue_as_new(self._build_resumed_input(input, sandbox_id))
                event = await self._wait_for_event()
                match event:
                    case TaskEvent.TIMEOUT_REACHED:
                        timeout_event = event
                        break
                    case TaskEvent.MAX_DURATION_REACHED:
                        workflow.logger.warning(
                            "max_run_duration_reached",
                            extra={"run_id": self.context.run_id},
                        )
                        timeout_event = event
                        break
                    case TaskEvent.CI_FOLLOW_UP:
                        workflow.logger.info(
                            "CI follow-up event triggered",
                            extra={"run_id": self.context.run_id, "repetitions": self._ci_repetitions},
                        )
                        _deprecate_ci_follow_up_pr_context_patch()
                        follow_up_result = await self._should_run_ci_follow_up()
                        if (
                            not self._ci_resume_snapshot_created
                            # Both terminal outcomes end the CI loop, so a resume snapshot here is
                            # wasted — the teardown pass snapshots the same case with pruning.
                            and follow_up_result not in (CIFollowUpDecision.NO_PR, CIFollowUpDecision.TERMINAL)
                            and self.context.mode == "interactive"
                            and self.context.use_modal_resume_snapshots
                            and workflow.patched(_PATCH_ID_SNAPSHOT_BEFORE_CI_FOLLOW_UP)
                        ):
                            self._ci_resume_snapshot_created = await self._create_resume_snapshot(
                                sandbox_id,
                                reason="ci_follow_up",
                                allow_pruning=False,
                            )
                        match follow_up_result:
                            case CIFollowUpDecision.FIRE:
                                workflow.set_current_details("🔁 Re-checking the PR's CI and nudging the agent.")
                                self._ci_resume_snapshot_created = False
                                await self._dispatch_ci_follow_up()
                            case CIFollowUpDecision.NO_PR | CIFollowUpDecision.TERMINAL:
                                # No PR will ever appear — stop the CI loop entirely.
                                self._ci_repetitions = MAX_CI_REPETITIONS
                            case CIFollowUpDecision.SKIP:
                                # Bound the next get_pr_context call to +CI_FOLLOW_UP_DELAY.
                                # Without this, _wait_for_ci_follow_up returns immediately
                                # whenever last_active_time is older than the delay, and the
                                # workflow tight-loops calling GET /repos/.../pulls/{n}.
                                self._last_active_time = workflow.now()
                            case _:
                                raise ValueError(f"Unknown CIFollowUpDecision: {follow_up_result}")
                    case TaskEvent.SANDBOX_TTL_APPROACHING:
                        self._sandbox_ttl_snapshot_taken = True
                        deadline_started_at = workflow.now()
                        workflow.logger.info(
                            "sandbox_deadline_snapshot_started",
                            extra={
                                "run_id": self.context.run_id,
                                "sandbox_id": sandbox_id,
                                "ttl_expires_at": (
                                    self._sandbox_ttl_expires_at.isoformat() if self._sandbox_ttl_expires_at else None
                                ),
                            },
                        )
                        rotated_sandbox_id: str | None = None
                        routing_restored = True
                        rotation_snapshot_saved = False
                        rotation_reason: str | None = (
                            "no_sandbox" if not sandbox_id else self._sandbox_rotation_block_reason()
                        )
                        if rotation_reason is None:
                            rotation = await self._rotate_sandbox_before_deadline(
                                sandbox_id, relay_task, credential_refresh_task
                            )
                            rotated_sandbox_id = rotation.sandbox_id
                            relay_task = rotation.relay_task
                            credential_refresh_task = rotation.credential_refresh_task
                            routing_restored = rotation.routing_restored
                            rotation_snapshot_saved = rotation.snapshot_saved
                            rotation_reason = rotation.reason
                        if rotated_sandbox_id:
                            sandbox_id = rotated_sandbox_id
                            if self._dev_stack_preview_enabled and _dev_stack_preview_enabled():
                                if preview_task is not None:
                                    await self._cancel_relay(preview_task)
                                preview_task = self._start_dev_stack_preview(sandbox_id)
                            await self._emit_progress(
                                step="sandbox_deadline",
                                status="completed",
                                label="Moved to a fresh sandbox",
                                group="sandbox-deadline",
                                detail="This session reached its sandbox time limit and carried on in a new one.",
                            )
                            deadline_outcome = "rotated"
                        else:
                            saved = rotation_snapshot_saved or bool(
                                sandbox_id
                                and await self._create_resume_snapshot(
                                    sandbox_id,
                                    reason="ttl_expiry",
                                    allow_pruning=False,
                                )
                            )
                            if not routing_restored:
                                detail = (
                                    "This run can't take more messages: moving it to a fresh sandbox failed "
                                    "part way. Start a new run to carry on."
                                    if saved
                                    else "This run can't take more messages, and the session could not be "
                                    "saved. Copy anything you still need from it."
                                )
                            elif saved:
                                detail = (
                                    "Sandboxes run for a fixed time and this one is near its limit. "
                                    "The session has been saved, so start a new run to pick it up."
                                )
                            else:
                                detail = (
                                    "Sandboxes run for a fixed time and this one is near its limit. "
                                    "The session could not be saved, so copy anything you still need from it."
                                )
                            await self._emit_progress(
                                step="sandbox_deadline",
                                status="in_progress" if saved and routing_restored else "failed",
                                label="This sandbox stops soon",
                                group="sandbox-deadline",
                                detail=detail,
                            )
                            if not routing_restored:
                                deadline_outcome = "routing_lost"
                            else:
                                deadline_outcome = "snapshot_only" if saved else "snapshot_failed"
                        await self._report_sandbox_deadline_outcome(
                            outcome=deadline_outcome,
                            reason=rotation_reason,
                            duration=workflow.now() - deadline_started_at,
                        )
                    case TaskEvent.QUOTA_RECHECK:
                        self._self_driving_quota_next_check_at = workflow.now() + SELF_DRIVING_QUOTA_RECHECK_INTERVAL
                        try:
                            quota_outcome = await workflow.execute_activity(
                                enforce_self_driving_run_quota,
                                EnforceSelfDrivingRunQuotaInput(
                                    run_id=self.context.run_id,
                                    task_id=self.context.task_id,
                                    team_id=self.context.team_id,
                                ),
                                start_to_close_timeout=timedelta(minutes=2),
                                retry_policy=RetryPolicy(maximum_attempts=2),
                            )
                        except Exception:
                            # A failed quota check must never kill a healthy run; the next
                            # recheck (or the quota cron) is the backstop.
                            workflow.logger.warning(
                                "Self-driving quota recheck activity failed, continuing",
                                extra={"run_id": self.context.run_id},
                            )
                            continue
                        if quota_outcome == SELF_DRIVING_QUOTA_STOP_CHECKING:
                            self._self_driving_quota_checks_active = False
                        elif quota_outcome == SELF_DRIVING_QUOTA_CANCELLED:
                            self._self_driving_quota_checks_active = False
                            # The cancel path already signalled complete_task; set the fields
                            # here as well so loop exit doesn't depend on signal delivery order.
                            if not self._task_completed:
                                self._completion_status = "cancelled"
                                self._completion_error = (
                                    "Stopped automatically: the organization reached its "
                                    "self-driving pull request limit."
                                )
                                self._task_completed = True
                    case TaskEvent.SANDBOX_GONE:
                        self._mark_sandbox_gone()
                    case TaskEvent.SIGNAL_RECEIVED:
                        if workflow.patched(_PATCH_ID_CONCURRENT_FOLLOWUP_STEERING):
                            if self._has_dispatchable_followup():
                                pending_followup_count = len(self._pending_followups) + (
                                    1 if self._pending_followup is not None else 0
                                )
                                workflow.logger.info(
                                    "Pending follow-up message received, sending to sandbox",
                                    extra={
                                        "run_id": self.context.run_id,
                                        "pending_followup_count": pending_followup_count,
                                    },
                                )
                            if await self._dispatch_next_followup():
                                continue
                        else:
                            pending_followup_count = len(self._pending_followups) + (
                                1 if self._pending_followup is not None else 0
                            )
                            if pending_followup_count == 0:
                                pending_followup = None
                            elif self._pending_followup is not None:
                                pending_followup = self._pending_followup
                                self._pending_followup = None
                            else:
                                pending_followup = self._pending_followups.pop(0)
                            if pending_followup is not None:
                                workflow.logger.info(
                                    "Pending follow-up message received, sending to sandbox",
                                    extra={
                                        "run_id": self.context.run_id,
                                        "pending_followup_count": pending_followup_count,
                                    },
                                )
                                await self._dispatch_followup(pending_followup)
                                continue

                        if self._heartbeat_received and not self._task_completed:
                            workflow.logger.info(
                                "Heartbeat received, resetting inactivity timer",
                                extra={"run_id": self.context.run_id},
                            )
                            self._heartbeat_received = False
                            self._client_activity_received = False
                            continue

                        if self._client_activity_received and not self._task_completed:
                            workflow.logger.info(
                                "Client activity received, resetting inactivity timer",
                                extra={"run_id": self.context.run_id},
                            )
                            self._client_activity_received = False
                            continue
                    case _:
                        raise ValueError(f"Unknown event type: {event}")

            # Cancel background loops as soon as the run ends, not just in `finally` —
            # a hang in the cleanup path below must not leave credential refresh running.
            await self._finish_active_followup()
            if relay_task is not None:
                await self._cancel_relay(relay_task)
            if credential_refresh_task is not None:
                await self._cancel_relay(credential_refresh_task)
                credential_refresh_task = None
            if permission_response_task is not None:
                if self._task_completed:
                    # The drainer exits on its own once the queue is empty, so a response
                    # that raced the completion signal is delivered (or its failure
                    # surfaced in the thread) instead of silently dropped.
                    await permission_response_task
                else:
                    await self._cancel_relay(permission_response_task)
                permission_response_task = None

            if self._task_completed:
                await self._update_task_run_status(
                    self._completion_status,
                    error_message=self._completion_error,
                    error_type=self._completion_error_type,
                    timeout_marker=self._completion_timeout_marker,
                )
            elif timeout_event == TaskEvent.MAX_DURATION_REACHED:
                # Only reachable under the lifecycle-bounds patch (the timer is gated on it).
                # A run that outlived the hard cap is a failure, not a completion, and the
                # state marker carries the reason so error_message stays empty.
                await self._update_task_run_status("failed", timeout_marker=TIMED_OUT_WALL_CLOCK_STATE_KEY)
            elif timeout_event is not None:
                inactivity_status = "failed" if self._onboarding_exit_is_failure() else "completed"
                await self._update_task_run_status(inactivity_status, timed_out_inactivity=True)

            # Close out the keep-it-green step so a finished run doesn't show a still-spinning CI step.
            if self._pr_progress_emitted:
                await self._emit_progress("ci", "completed", "Keeping CI green", "setup")

            await self._post_slack_update()

            return ProcessTaskOutput(
                success=True,
                task_result=None,
                error=None,
                sandbox_id=sandbox_id,
            )

        except asyncio.CancelledError:
            current_sandbox_id = sandbox_id or self._sandbox_id_for_cleanup
            if self._context:
                if self._current_progress_step is not None:
                    failed_step, failed_label, failed_group = self._current_progress_step
                    await self._emit_progress(
                        failed_step,
                        "failed",
                        failed_label,
                        failed_group,
                        detail="Cancelled",
                    )
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
                complete_stream = _defer_run_stream_completion()
                await self._cleanup_sandbox(
                    current_sandbox_id,
                    complete_stream=complete_stream,
                )
                run_stream_completed = complete_stream
                sandbox_id = None
                self._sandbox_id_for_cleanup = None
            raise

        except _TaskCompletedDuringSandboxCreation:
            await self._update_task_run_status(
                self._completion_status,
                error_message=self._completion_error,
                error_type=self._completion_error_type,
                timeout_marker=self._completion_timeout_marker,
            )
            if self._context:
                await self._post_slack_update()
            return ProcessTaskOutput(
                success=True,
                task_result=None,
                error=None,
                sandbox_id=None,
            )

        except Exception as e:
            current_sandbox_id = sandbox_id or self._sandbox_id_for_cleanup
            # str(ActivityError) is Temporal's opaque "Activity task failed" wrapper; Slack and
            # the UI show the persisted message, so surface the cause instead.
            cause = e.cause if isinstance(e, temporalio.exceptions.ActivityError) else None
            cause_message = getattr(cause, "message", None) or (str(cause) if cause is not None else None)
            error_type = _failure_error_type(cause, e)
            error_message = truncate_error_message(cause_message or str(e))
            if self._context:
                if self._current_progress_step is not None:
                    failed_step, failed_label, failed_group = self._current_progress_step
                    await self._emit_progress(
                        failed_step,
                        "failed",
                        failed_label,
                        failed_group,
                        detail=error_message[:200],
                    )
                # Metrics and logs only: the status-update activity below owns the
                # task_run_failed analytics capture, keyed on the DB transition.
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
                        "error_message": truncate_error_message(str(e)),
                        "sandbox_id": current_sandbox_id,
                        **self._activity_error_properties(e),
                    },
                    capture_analytics=False,
                )
            await self._update_task_run_status(
                "failed", error_message=error_message, run_id=run_id, error_type=error_type
            )
            if self._context:
                await self._post_slack_update()

            return ProcessTaskOutput(
                success=False,
                task_result=None,
                error=error_message,
                sandbox_id=current_sandbox_id,
            )

        finally:
            # Skip teardown on a continue_as_new hand-off (a `return` here would swallow the
            # ContinueAsNewError); the loops are already stopped and the sandbox lives on.
            if not continuing_as_new:
                if self._active_followup_task is not None:
                    await self._cancel_relay(self._active_followup_task)
                    self._active_followup_task = None
                if credential_refresh_task is not None:
                    await self._cancel_relay(credential_refresh_task)
                if permission_response_task is not None:
                    await self._cancel_relay(permission_response_task)
                if preview_task is not None:
                    await self._cancel_relay(preview_task)
                await self._close_dev_stack_preview_progress()

                cleanup_sandbox_id = sandbox_id or self._sandbox_id_for_cleanup
                if cleanup_sandbox_id:
                    if (
                        self._context
                        and self._context.mode == "interactive"
                        and self._context.use_modal_resume_snapshots
                    ):
                        await self._create_resume_snapshot(
                            cleanup_sandbox_id,
                            reason="teardown",
                            allow_pruning=True,
                        )

                    await self._read_sandbox_logs(cleanup_sandbox_id)
                    await self._cleanup_sandbox(
                        cleanup_sandbox_id,
                        complete_stream=_defer_run_stream_completion(),
                    )
                    sandbox_cleaned = True
                    self._sandbox_id_for_cleanup = None
                elif not run_stream_completed and (
                    (self._context is None or self._context.environment == "cloud") and _defer_run_stream_completion()
                ):
                    await self._complete_run_stream(run_id)

                if sandbox_cleaned and self._slack_thread_context and self._context:
                    await self._post_slack_update(sandbox_cleaned=True)

    async def _provision_and_start_agent(self, input: ProcessTaskInput, run_id: str) -> tuple[str, str, str | None]:
        """Initial-run setup: resolve agent-design, provision the sandbox, start the agent
        server. Returns (sandbox_id, sandbox_url, connect_token). Skipped on continue_as_new."""
        # See _PATCH_ID_SLACK_AGENT_DESIGN_STATUS. Short-circuit on
        # ``_slack_thread_context`` so non-Slack runs never call the
        # workflow-scoped ``workflow.patched`` API (unit tests that
        # invoke ``run`` outside a Temporal event loop would otherwise
        # raise "Not in workflow event loop" here). Skipping the marker
        # is safe: ``_resolve_agent_design_flag`` itself returns False
        # for these runs, so recording the patch would have no
        # observable effect on their behavior.
        if self._slack_thread_context and workflow.patched(_PATCH_ID_SLACK_AGENT_DESIGN_STATUS):
            self._is_agent_design_enabled = await self._resolve_agent_design_flag()
        await self._update_task_run_status("in_progress")

        # Announce the first progress step immediately so the desktop card
        # shows up before any provisioning log lines arrive.
        sandbox_label = "Restoring sandbox" if self.context.is_snapshot_resume else "Setting up sandbox"
        await self._emit_progress("sandbox", "in_progress", sandbox_label, "setup")

        await self._track_workflow_event(
            "task_run_started",
            {
                "run_id": run_id,
                "task_id": self.context.task_id,
                "repository": self.context.repository,
                "team_id": self.context.team_id,
                "loop_id": self.context.loop_id,
                "loop_trigger_id": self.context.loop_trigger_id,
            },
        )

        # Agent-design path owns this surface via per-turn relay children.
        if not self._is_agent_design_enabled:
            await self._post_slack_update()

        sandbox_output = await self._get_sandbox_for_repository()
        sandbox_id = sandbox_output.sandbox_id

        # TODO(tasks): Re-enable snapshot creation
        # if sandbox_output.should_create_snapshot and self.context.repository and self.context.github_integration_id:
        #     await self._trigger_snapshot_workflow()

        # See `_PATCH_ID_DROP_SLACK_POST_AFTER_PROVISIONING`: only replays of
        # pre-rollout histories still post here; new executions skip the
        # redundant update to keep determinism for in-flight workflows.
        if not workflow.patched(_PATCH_ID_DROP_SLACK_POST_AFTER_PROVISIONING):
            if not self._is_agent_design_enabled:
                await self._post_slack_update()

        # Run the PostHog setup wizard before the agent, when this is a cloud wizard run.
        # The wizard integrates PostHog and dirties the working tree; the agent then commits
        # those changes, opens the PR, and keeps it green (it never implements PostHog itself).
        wizard_ms = await self._run_wizard_if_configured(sandbox_output)

        # Start agent-server for direct connection from PostHog Desktop
        if sandbox_output.agent_server_launched:
            agent_server_output = await self._await_agent_server_ready(sandbox_output, boot_excluded_ms=wizard_ms)
        else:
            await self._emit_progress("agent", "in_progress", "Starting agent", "setup")
            agent_server_output = await self._start_agent_server(sandbox_output, boot_excluded_ms=wizard_ms)
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
                "boot_path": sandbox_output.boot_path,
                "image_source": sandbox_output.image_source,
                "boot_total_ms": agent_server_output.boot_total_ms,
                "sandbox_create_ms": sandbox_output.create_ms,
                "repo_clone_ms": sandbox_output.clone_ms,
                "branch_checkout_ms": sandbox_output.checkout_ms,
                "agent_launch_ms": sandbox_output.launch_ms,
                "agent_ready_wait_ms": agent_server_output.ready_wait_ms,
                "agent_session_init_ms": agent_server_output.session_init_ms,
                "agent_context_fetch_ms": agent_server_output.boot_phases_ms.get("context_fetch"),
                "agent_acp_initialize_ms": agent_server_output.boot_phases_ms.get("acp_initialize"),
                "agent_repository_ready_ms": agent_server_output.boot_phases_ms.get("repository_ready"),
                "agent_session_dependencies_ms": agent_server_output.boot_phases_ms.get("session_dependencies"),
                "agent_session_create_ms": agent_server_output.boot_phases_ms.get("session_create"),
                "agent_shadow_launched": agent_server_output.shadow_observation.get("launched"),
                "agent_shadow_outcome": agent_server_output.shadow_observation.get("outcome"),
                "agent_shadow_observed_ready_ms": agent_server_output.shadow_observation.get("observed_ready_ms"),
                "agent_shadow_production_ready_ms": agent_server_output.shadow_observation.get("production_ready_ms"),
                "agent_shadow_failure_class": agent_server_output.shadow_observation.get("failure_class"),
                "agent_shadow_read_timed_out": agent_server_output.shadow_observation.get("timed_out"),
                "loop_id": self.context.loop_id,
                "loop_trigger_id": self.context.loop_trigger_id,
            },
        )
        return sandbox_id, agent_server_output.sandbox_url, agent_server_output.connect_token

    def _should_continue_as_new(self, sandbox_id: str | None) -> bool:
        # Only from a clean idle point — no queued work and no live Slack relay child (which
        # is cancelled on parent close). Gated on the start-captured flag so in-flight runs
        # (decoding it to False) and the trigger stay deterministic across replay.
        if self._context is None or not self.context.continue_as_new_enabled or sandbox_id is None:
            return False
        if self._task_completed or self._sandbox_gone:
            return False
        if (
            self._pending_followup is not None
            or self._pending_followups
            or self._pending_permission_responses
            or self._heartbeat_received
            or self._client_activity_received
            or self._current_slack_relay_workflow_id is not None
        ):
            return False
        threshold = self.context.continue_as_new_history_threshold
        if threshold and workflow.info().get_current_history_length() >= threshold:
            return True
        return workflow.info().is_continue_as_new_suggested()

    def _build_resumed_input(self, input: ProcessTaskInput, sandbox_id: str) -> ProcessTaskInput:
        return ProcessTaskInput(
            run_id=input.run_id,
            create_pr=input.create_pr,
            slack_thread_context=self._slack_thread_context,
            posthog_mcp_scopes=self._posthog_mcp_scopes,
            prewarmed=False,
            resumed_sandbox=ResumedSandboxState(
                sandbox_id=sandbox_id,
                sandbox_url=self._sandbox_url or "",
                connect_token=self._sandbox_connect_token,
                jwt_kid=self._sandbox_jwt_kid,
                ci_repetitions=self._ci_repetitions,
                pr_fingerprint=self._pr_fingerprint,
                pr_unresolved_threads=self._pr_unresolved_threads,
                babysit_journal=self._babysit_journal,
                pr_progress_emitted=self._pr_progress_emitted,
                ci_resume_snapshot_created=self._ci_resume_snapshot_created,
                first_user_message_received=self._first_user_message_received,
                is_agent_design_enabled=self._is_agent_design_enabled,
                dev_stack_preview_enabled=self._dev_stack_preview_enabled,
                last_active_time=self._last_active_time.isoformat() if self._last_active_time else None,
                accepted_message_ids=self._accepted_message_ids,
                chain_started_at=self._chain_start_time().isoformat(),
                agent_active=self._agent_active,
                end_of_turn_received=self._end_of_turn_received,
                last_agent_heartbeat_at=(
                    self._last_agent_heartbeat_at.isoformat() if self._last_agent_heartbeat_at else None
                ),
                sandbox_ttl_expires_at=(
                    self._sandbox_ttl_expires_at.isoformat() if self._sandbox_ttl_expires_at else None
                ),
                sandbox_ttl_snapshot_taken=self._sandbox_ttl_snapshot_taken,
            ),
        )

    def _chain_start_time(self) -> datetime:
        """Start of the continue_as_new chain, falling back to this run's start time.

        `workflow.info().start_time` is per-run, so a continuation would otherwise restart
        the wall-clock cap from zero, and continuations are triggered by history growth,
        which heartbeats drive.
        """
        return self._chain_started_at or workflow.info().start_time

    def _restore_resumed_state(self, resumed: ResumedSandboxState) -> None:
        self._chain_started_at = datetime.fromisoformat(resumed.chain_started_at) if resumed.chain_started_at else None
        self._is_agent_design_enabled = resumed.is_agent_design_enabled
        self._dev_stack_preview_enabled = resumed.dev_stack_preview_enabled
        self._ci_repetitions = resumed.ci_repetitions
        self._pr_fingerprint = resumed.pr_fingerprint
        self._pr_unresolved_threads = resumed.pr_unresolved_threads
        self._babysit_journal = resumed.babysit_journal
        self._pr_progress_emitted = resumed.pr_progress_emitted
        self._ci_resume_snapshot_created = resumed.ci_resume_snapshot_created
        self._first_user_message_received = resumed.first_user_message_received
        self._accepted_message_ids = resumed.accepted_message_ids
        self._accepted_message_id_set = set(resumed.accepted_message_ids)
        self._last_active_time = datetime.fromisoformat(resumed.last_active_time) if resumed.last_active_time else None
        self._agent_active = resumed.agent_active
        self._end_of_turn_received = resumed.end_of_turn_received
        self._last_agent_heartbeat_at = (
            datetime.fromisoformat(resumed.last_agent_heartbeat_at) if resumed.last_agent_heartbeat_at else None
        )
        self._sandbox_ttl_expires_at = (
            datetime.fromisoformat(resumed.sandbox_ttl_expires_at) if resumed.sandbox_ttl_expires_at else None
        )
        self._sandbox_ttl_snapshot_taken = resumed.sandbox_ttl_snapshot_taken

    async def _get_task_processing_context(self, input: ProcessTaskInput) -> TaskProcessingContext:
        context = await workflow.execute_activity(
            get_task_processing_context,
            GetTaskProcessingContextInput(run_id=input.run_id, create_pr=input.create_pr),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        return context

    async def _get_sandbox_for_repository(self) -> GetSandboxForRepositoryOutput:
        prepared = await workflow.execute_activity(
            prepare_sandbox_for_repository,
            PrepareSandboxForRepositoryInput(context=self.context),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        created = await self._run_sandbox_creation_activity(prepared)
        self._sandbox_id_for_cleanup = created.sandbox_id
        self._sandbox_jwt_kid = created.jwt_kid
        self._dev_stack_preview_enabled = self._dev_stack_preview_enabled and created.dev_stack_preview_sized
        self._record_sandbox_deadline(created)
        if (
            self._task_completed
            and prepared.sandbox_creation_cancellable
            and workflow.patched(_PATCH_ID_CANCEL_SANDBOX_CREATION_ON_COMPLETION)
        ):
            raise _TaskCompletedDuringSandboxCreation
        used_snapshot = created.used_snapshot if created.used_snapshot is not None else prepared.used_snapshot
        if used_snapshot:
            await self._emit_progress(
                "sandbox",
                "completed",
                "Restored sandbox",
                "setup",
                detail="Resumed from a previous snapshot",
            )
        else:
            await self._emit_progress("sandbox", "completed", "Set up sandbox", "setup")

        # Resuming from a filesystem snapshot carries the previous run's
        # credentials baked into .git/config and any agentsh env file — refresh
        # them before any sandbox command (diagnostics, fetch, checkout) runs.
        if used_snapshot and prepared.snapshot_external_id:
            try:
                await workflow.execute_activity(
                    inject_fresh_tokens_on_resume,
                    InjectFreshTokensOnResumeInput(
                        context=self.context,
                        sandbox_id=created.sandbox_id,
                        repository=prepared.repository,
                    ),
                    start_to_close_timeout=timedelta(minutes=2),
                    # A dead sandbox won't come back; fail fast into the fallback below.
                    retry_policy=RetryPolicy(
                        maximum_attempts=3,
                        non_retryable_error_types=list(DEAD_SANDBOX_ERROR_TYPES),
                    ),
                )
            except Exception as e:
                # Only a dead restored sandbox falls back: drop the poison snapshot, discard the
                # sandbox, and provision fresh (the agent resumes from run-log history, not the
                # filesystem). Anything else — e.g. credential failures — would hit a fresh
                # sandbox too, so let it fail the run without trashing a valid snapshot.
                if not _is_dead_sandbox_failure(e):
                    raise
                workflow.logger.warning(
                    "resume_restore_failed_falling_back_to_fresh_sandbox",
                    extra={
                        "run_id": self.context.run_id,
                        "sandbox_id": created.sandbox_id,
                        "snapshot_external_id": prepared.snapshot_external_id,
                        "error": str(e),
                        **self._activity_error_properties(e),
                    },
                )
                await workflow.execute_activity(
                    invalidate_resume_snapshot,
                    InvalidateResumeSnapshotInput(
                        run_id=self.context.run_id,
                        snapshot_external_id=prepared.snapshot_external_id,
                    ),
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                self._resume_snapshot_invalidated = True
                await self._cleanup_sandbox(created.sandbox_id)
                self._sandbox_id_for_cleanup = None
                fresh_image_source, fresh_image_source_label = get_fresh_image_source_for_context(self.context)
                prepared = replace(
                    prepared,
                    snapshot_id=None,
                    snapshot_external_id=None,
                    used_snapshot=False,
                    should_create_snapshot=True,
                    snapshot_kind=SNAPSHOT_KIND_FILESYSTEM,
                    snapshot_mount_path=None,
                    snapshot_source="none",
                    image_source=fresh_image_source,
                    image_source_label=fresh_image_source_label,
                )
                await self._emit_progress(
                    "sandbox",
                    "in_progress",
                    "Setting up sandbox",
                    "setup",
                    detail="Previous session could not be restored; starting fresh",
                )
                created = await self._run_sandbox_creation_activity(prepared)
                self._sandbox_id_for_cleanup = created.sandbox_id
                self._sandbox_jwt_kid = created.jwt_kid
                self._dev_stack_preview_enabled = self._dev_stack_preview_enabled and created.dev_stack_preview_sized
                self._record_sandbox_deadline(created)
                if (
                    self._task_completed
                    and prepared.sandbox_creation_cancellable
                    and workflow.patched(_PATCH_ID_CANCEL_SANDBOX_CREATION_ON_COMPLETION)
                ):
                    raise _TaskCompletedDuringSandboxCreation
                used_snapshot = False
                await self._emit_progress("sandbox", "completed", "Set up sandbox", "setup")

        can_clone_without_integration = is_public_sandbox_repo(prepared.repository)
        has_clone_credentials = self.context.has_github_credentials or can_clone_without_integration

        repositories_to_clone = [] if used_snapshot or not has_clone_credentials else self.context.repositories
        will_clone = bool(repositories_to_clone)
        checkout_repository = self.context.repositories[0] if len(self.context.repositories) == 1 else None
        will_checkout = bool(checkout_repository and prepared.branch and has_clone_credentials)

        def prepares_desktop(repository: str) -> bool:
            return self.context.custom_image_name == DEV_STACK_IMAGE_NAME and repository.casefold() == "posthog/posthog"

        overlap = bool(self.context.overlap_clone_boot_enabled and will_clone)
        boot_path = "overlap" if overlap else "classic"
        launch_ms: int | None = None
        if overlap:
            await self._emit_progress("agent", "in_progress", "Starting agent", "setup")
            launch_output = await self._launch_agent_server(created, defer_for_clone=True, used_snapshot=used_snapshot)
            launch_ms = launch_output.launch_ms if launch_output else None

        clone_ms: int | None = None
        failed_repositories: set[str] = set()
        materialized_failed_repositories: set[str] = set()
        repo_ready_released = False
        release_after_primary_clone = bool(
            overlap and len(repositories_to_clone) > 1 and workflow.patched(_PATCH_ID_AGENT_READY_AFTER_PRIMARY_CLONE)
        )
        if will_clone:
            await self._emit_progress("clone", "in_progress", "Cloning repository", "setup")
            continue_after_clone_failure = workflow.patched(_PATCH_ID_CONTINUE_AFTER_REPOSITORY_CLONE_FAILURE)

            async def clone_repository(
                repository: str,
            ) -> tuple[CloneRepositoryInSandboxOutput | None, bool, bool]:
                prepares_repository_desktop = prepares_desktop(repository)
                try:
                    clone_output = await workflow.execute_activity(
                        clone_repository_in_sandbox,
                        CloneRepositoryInSandboxInput(
                            context=self.context,
                            sandbox_id=created.sandbox_id,
                            repository=repository,
                            github_token=prepared.github_token,
                            shallow_clone=prepared.shallow_clone,
                        ),
                        start_to_close_timeout=(
                            _DESKTOP_BOOTSTRAP_ACTIVITY_TIMEOUT if prepares_repository_desktop else timedelta(minutes=5)
                        ),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )
                except Exception as error:
                    if _is_dead_sandbox_failure(error) or not continue_after_clone_failure:
                        raise
                    workflow.logger.warning(
                        "repository_clone_failed_continuing_without_repository",
                        extra={
                            "run_id": self.context.run_id,
                            "sandbox_id": created.sandbox_id,
                            "repository": repository,
                            "error": str(error),
                        },
                    )
                    clone_output = None
                    clone_failed = True
                else:
                    clone_failed = False

                is_primary_repository = repository == repositories_to_clone[0]
                should_release_after_clone = release_after_primary_clone and is_primary_repository
                should_materialize_failure = release_after_primary_clone and clone_failed
                if should_release_after_clone or should_materialize_failure:
                    await self._mark_repo_ready(
                        created.sandbox_id,
                        failed_repositories=[repository] if clone_failed else None,
                        release_barrier=should_release_after_clone,
                    )
                return clone_output, clone_failed, should_release_after_clone

            clone_outputs = await asyncio.gather(
                *(clone_repository(repository) for repository in repositories_to_clone)
            )
            clone_durations: list[int] = []
            for repository, (clone_output, clone_failed, released_after_clone) in zip(
                repositories_to_clone, clone_outputs
            ):
                if clone_failed:
                    failed_repositories.add(repository)
                    if release_after_primary_clone:
                        materialized_failed_repositories.add(repository)
                repo_ready_released = repo_ready_released or released_after_clone
                if (duration := getattr(clone_output, "clone_ms", None)) is not None:
                    clone_durations.append(duration)
            clone_ms = sum(clone_durations) if clone_durations else None
            if failed_repositories:
                failed_list = ", ".join(sorted(failed_repositories))
                remaining_failed_repositories = sorted(failed_repositories - materialized_failed_repositories)
                should_release_barrier = overlap and not repo_ready_released
                if remaining_failed_repositories or should_release_barrier:
                    await self._mark_repo_ready(
                        created.sandbox_id,
                        failed_repositories=remaining_failed_repositories or None,
                        release_barrier=should_release_barrier,
                    )
                    repo_ready_released = repo_ready_released or should_release_barrier
                await self._emit_progress(
                    "clone",
                    "completed",
                    "Repository clone failed; continuing without it",
                    "setup",
                    detail=f"Could not clone: {failed_list}",
                )
            else:
                clone_label = "Cloned repository" if len(repositories_to_clone) == 1 else "Cloned repositories"
                await self._emit_progress("clone", "completed", clone_label, "setup")

        state = self.context.state or {}
        is_resume = bool(state.get("resume_from_run_id") or is_same_run_resume_state(state))
        checkout_ms: int | None = None
        if will_checkout and checkout_repository not in failed_repositories and not is_resume:
            assert checkout_repository is not None
            assert prepared.branch is not None
            prepares_repository_desktop = prepares_desktop(checkout_repository)
            branch_label_active = f"Checking out branch {prepared.branch}"
            branch_label_done = f"Checked out branch {prepared.branch}"
            await self._emit_progress("checkout", "in_progress", branch_label_active, "setup")
            checkout_output = await workflow.execute_activity(
                checkout_branch_in_sandbox,
                CheckoutBranchInSandboxInput(
                    context=self.context,
                    sandbox_id=created.sandbox_id,
                    repository=checkout_repository,
                    branch=prepared.branch,
                    github_token=prepared.github_token,
                    shallow_clone=prepared.shallow_clone,
                    used_snapshot=used_snapshot,
                ),
                start_to_close_timeout=(
                    _DESKTOP_BOOTSTRAP_ACTIVITY_TIMEOUT if prepares_repository_desktop else timedelta(minutes=5)
                ),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            # Pre-rollout histories (and mocked tests) recorded a null result here.
            checkout_ms = getattr(checkout_output, "checkout_ms", None)
            await self._emit_progress("checkout", "completed", branch_label_done, "setup")

        # Gated on recorded activity output, not workflow.patched: the env var only
        # exists in histories written after the context layer shipped, so replays of
        # pre-rollout histories skip this command deterministically.
        if prepared.environment_variables.get("POSTHOG_CONTEXT_LAYER_PATH"):
            await workflow.execute_activity(
                materialize_context_layer_in_sandbox,
                MaterializeContextLayerInput(context=self.context, sandbox_id=created.sandbox_id),
                start_to_close_timeout=timedelta(minutes=3),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

        if overlap and not repo_ready_released:
            await self._mark_repo_ready(created.sandbox_id)

        return GetSandboxForRepositoryOutput(
            sandbox_id=created.sandbox_id,
            sandbox_url=created.sandbox_url,
            connect_token=created.connect_token,
            used_snapshot=used_snapshot,
            should_create_snapshot=not used_snapshot,
            jwt_kid=created.jwt_kid,
            agent_server_launched=overlap,
            boot_path=boot_path,
            image_source=prepared.image_source,
            create_ms=created.create_ms,
            clone_ms=clone_ms,
            checkout_ms=checkout_ms,
            launch_ms=launch_ms,
            dev_stack_preview_sized=created.dev_stack_preview_sized,
        )

    async def _run_sandbox_creation_activity(
        self, prepared: PrepareSandboxForRepositoryOutput
    ) -> CreateSandboxForRepositoryOutput:
        activity_input = CreateSandboxForRepositoryInput(context=self.context, prepared=prepared)
        creation_timeout = timedelta(seconds=prepared.sandbox_creation_timeout_seconds)
        retry_policy = RetryPolicy(maximum_attempts=3)
        if not prepared.sandbox_creation_cancellable or not workflow.patched(
            _PATCH_ID_CANCEL_SANDBOX_CREATION_ON_COMPLETION
        ):
            return await workflow.execute_activity(
                create_sandbox_for_repository,
                activity_input,
                start_to_close_timeout=creation_timeout,
                retry_policy=retry_policy,
            )

        creation = workflow.start_activity(
            create_sandbox_for_repository,
            activity_input,
            cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            heartbeat_timeout=timedelta(seconds=30),
            start_to_close_timeout=creation_timeout,
            retry_policy=retry_policy,
        )
        completion = asyncio.create_task(workflow.wait_condition(lambda: self._task_completed))
        done, _ = await asyncio.wait({creation, completion}, return_when=asyncio.FIRST_COMPLETED)
        if creation in done:
            completion.cancel()
            try:
                await completion
            except asyncio.CancelledError:
                pass
            return await creation

        creation.cancel()
        try:
            await creation
        except (asyncio.CancelledError, temporalio.exceptions.ActivityError):
            pass
        raise _TaskCompletedDuringSandboxCreation

    async def _cleanup_sandbox(self, sandbox_id: str, *, complete_stream: bool = False) -> None:
        context = self._context
        cleanup_input = CleanupSandboxInput(
            sandbox_id=sandbox_id,
            run_id=context.run_id if context else None,
            complete_stream_on_cleanup=bool(context and complete_stream),
        )
        try:
            await workflow.execute_activity(
                cleanup_sandbox,
                cleanup_input,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except Exception:
            if context and complete_stream and _complete_stream_after_cleanup_failure():
                await self._complete_run_stream(context.run_id)
            raise

    async def _complete_run_stream(self, run_id: str) -> None:
        await workflow.execute_activity(
            complete_run_stream,
            CompleteRunStreamInput(run_id=run_id),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _read_sandbox_logs(self, sandbox_id: str) -> None:
        try:
            logs = await workflow.execute_activity(
                read_sandbox_logs,
                ReadSandboxLogsInput(sandbox_id=sandbox_id, run_id=self.context.run_id),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            if logs:
                workflow.logger.info(f"Agent-server logs from sandbox {sandbox_id}:\n{logs}")
        except Exception as e:
            workflow.logger.warning(f"Failed to read sandbox logs: {e}")

    async def _run_wizard_if_configured(self, sandbox_output: GetSandboxForRepositoryOutput) -> int:
        """Run the setup wizard in the sandbox before the agent, for cloud wizard runs only.

        Fails the run on a non-zero wizard exit (maximum_attempts=1, and the wizard is non-idempotent
        once it has modified files), rather than handing a half-integrated tree to the agent.
        """
        repository = self.context.repository
        # `is not None` (not truthiness): an empty config dict still means "this is a wizard run".
        if self.context.wizard_config is None or not repository:
            return 0

        exclude_from_boot_total = workflow.patched(_PATCH_ID_EXCLUDE_WIZARD_FROM_BOOT_TOTAL)
        await self._emit_progress("wizard", "in_progress", "Running PostHog setup wizard", "setup")
        started_at = workflow.now() if exclude_from_boot_total else None
        await workflow.execute_activity(
            run_wizard,
            RunWizardInput(
                context=self.context,
                sandbox_id=sandbox_output.sandbox_id,
                repository=repository,
            ),
            # Above WIZARD_RUN_TIMEOUT_SECONDS (45 min) so the wizard's own timeout bounds the run;
            # the headroom covers the sandbox lookup and writing the output log.
            start_to_close_timeout=timedelta(minutes=50),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        wizard_ms = int((workflow.now() - started_at).total_seconds() * 1000) if started_at is not None else 0
        await self._emit_progress("wizard", "completed", "Ran PostHog setup wizard", "setup")
        return wizard_ms

    @staticmethod
    def _workflow_start_at_iso() -> str | None:
        """Workflow start time for the boot-total metric; None outside a workflow event loop (unit tests)."""
        try:
            return workflow.info().start_time.isoformat()
        except Exception:
            return None

    async def _start_agent_server(
        self, sandbox_output: GetSandboxForRepositoryOutput, *, boot_excluded_ms: int = 0
    ) -> StartAgentServerOutput:
        return await workflow.execute_activity(
            start_agent_server,
            StartAgentServerInput(
                context=self.context,
                sandbox_id=sandbox_output.sandbox_id,
                sandbox_url=sandbox_output.sandbox_url,
                sandbox_connect_token=sandbox_output.connect_token,
                posthog_mcp_scopes=self._posthog_mcp_scopes,
                boot_path=sandbox_output.boot_path,
                used_snapshot=sandbox_output.used_snapshot,
                workflow_start_at=self._workflow_start_at_iso(),
                boot_excluded_ms=boot_excluded_ms,
            ),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _launch_agent_server(
        self, created: CreateSandboxForRepositoryOutput, *, defer_for_clone: bool, used_snapshot: bool | None = None
    ) -> StartAgentServerOutput:
        return await workflow.execute_activity(
            launch_agent_server,
            StartAgentServerInput(
                context=self.context,
                sandbox_id=created.sandbox_id,
                sandbox_url=created.sandbox_url,
                sandbox_connect_token=created.connect_token,
                posthog_mcp_scopes=self._posthog_mcp_scopes,
                defer_for_clone=defer_for_clone,
                boot_path="overlap",
                used_snapshot=used_snapshot,
            ),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _mark_repo_ready(
        self,
        sandbox_id: str,
        failed_repositories: list[str] | None = None,
        *,
        release_barrier: bool = True,
    ) -> None:
        await workflow.execute_activity(
            mark_repo_ready,
            MarkRepoReadyInput(
                sandbox_id=sandbox_id,
                run_id=self.context.run_id,
                failed_repositories=failed_repositories,
                release_barrier=release_barrier,
            ),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _await_agent_server_ready(
        self, sandbox_output: GetSandboxForRepositoryOutput, *, boot_excluded_ms: int = 0
    ) -> StartAgentServerOutput:
        return await workflow.execute_activity(
            await_agent_server_ready,
            StartAgentServerInput(
                context=self.context,
                sandbox_id=sandbox_output.sandbox_id,
                sandbox_url=sandbox_output.sandbox_url,
                sandbox_connect_token=sandbox_output.connect_token,
                posthog_mcp_scopes=self._posthog_mcp_scopes,
                boot_path=sandbox_output.boot_path,
                used_snapshot=sandbox_output.used_snapshot,
                workflow_start_at=self._workflow_start_at_iso(),
                boot_excluded_ms=boot_excluded_ms,
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

    async def _deliver_pending_permission_responses(self) -> None:
        """Drain queued human permission responses, concurrently with the main loop.

        Exits once the run completes and the queue is empty, so a response that
        raced the completion signal is still delivered.
        """
        while True:
            await workflow.wait_condition(lambda: len(self._pending_permission_responses) > 0 or self._task_completed)
            while self._pending_permission_responses:
                response = self._pending_permission_responses.pop(0)
                self._last_active_time = workflow.now()
                workflow.logger.info(
                    "Pending permission response received, sending to sandbox",
                    extra={
                        "run_id": self.context.run_id,
                        "request_id": response.request_id,
                        "option_id": response.option_id,
                        "actor_user_id": response.actor_user_id,
                        "is_denial": response.is_denial,
                    },
                )
                await self._send_permission_response_to_sandbox(response)
            if self._task_completed:
                return

    async def _send_permission_response_to_sandbox(self, response: PendingPermissionResponse) -> None:
        if response.is_denial and response.denial_message:
            # Best-effort and single-attempt: the guidance message is not idempotent,
            # so it must not share a retry boundary with the response delivery below,
            # and a failure to deliver it must not block the rejection itself.
            try:
                await workflow.execute_activity(
                    send_permission_denial_guidance,
                    SendPermissionDenialGuidanceInput(
                        run_id=self.context.run_id,
                        request_id=response.request_id,
                        actor_user_id=response.actor_user_id,
                        denial_message=response.denial_message,
                    ),
                    start_to_close_timeout=timedelta(seconds=20),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
            except Exception as e:
                workflow.logger.warning(
                    "permission_denial_guidance_failed",
                    extra={
                        "run_id": self.context.run_id,
                        "request_id": response.request_id,
                        "error": str(e),
                    },
                )

        try:
            await workflow.execute_activity(
                send_permission_response_to_sandbox,
                SendPermissionResponseToSandboxInput(
                    run_id=self.context.run_id,
                    request_id=response.request_id,
                    option_id=response.option_id,
                    actor_user_id=response.actor_user_id,
                    actor_slack_user_id=response.actor_slack_user_id,
                    is_denial=response.is_denial,
                    broker_reason=response.broker_reason,
                ),
                start_to_close_timeout=timedelta(seconds=45),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=5), maximum_attempts=3),
            )
        except Exception as e:
            # A failed delivery must not fail the run: the sandbox is usually still
            # healthy (transient tunnel blip) and the request can still be answered
            # from the task UI. The Slack card already shows the response as
            # recorded, so surface the miss in the thread instead.
            workflow.logger.warning(
                "permission_response_delivery_failed",
                extra={
                    "run_id": self.context.run_id,
                    "request_id": response.request_id,
                    "option_id": response.option_id,
                    "error": str(e),
                },
            )
            await self._notify_permission_delivery_failure(response)

    async def _notify_permission_delivery_failure(self, response: PendingPermissionResponse) -> None:
        if not self._slack_thread_context:
            return
        try:
            await workflow.execute_activity(
                post_permission_delivery_failure_notice,
                PostPermissionDeliveryFailureInput(
                    run_id=self.context.run_id,
                    request_id=response.request_id,
                    slack_thread_context=self._slack_thread_context,
                ),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except Exception as e:
            workflow.logger.warning(
                "permission_response_delivery_failure_notice_failed",
                extra={
                    "run_id": self.context.run_id,
                    "request_id": response.request_id,
                    "error": str(e),
                },
            )

    def _should_forward_pending_user_message(self) -> bool:
        if not self._context:
            return False

        state = self.context.state or {}
        is_resume = bool(state.get("resume_from_run_id") or is_same_run_resume_state(state))
        return self.context.mode != "interactive" and not is_resume

    async def _track_workflow_event(self, event_name: str, properties: dict, capture_analytics: bool = True) -> None:
        track_input = TrackWorkflowEventInput(
            event_name=event_name,
            distinct_id=self.context.distinct_id,
            properties=properties,
            groups={
                "organization": self.context.organization_id,
                "project": self.context.team_uuid,
            },
            capture_analytics=capture_analytics,
        )
        await workflow.execute_activity(
            track_workflow_event,
            track_input,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

    async def _report_sandbox_deadline_outcome(self, *, outcome: str, reason: str | None, duration: timedelta) -> None:
        """Report how a sandbox deadline resolved, for the rollout's metrics.

        Best-effort: a run that survived its deadline must not fail because the report did.
        """
        try:
            await self._track_workflow_event(
                SANDBOX_DEADLINE_EVENT,
                {
                    "run_id": self.context.run_id,
                    "task_id": self.context.task_id,
                    "team_id": self.context.team_id,
                    "origin_product": self.context.origin_product,
                    "outcome": outcome,
                    "reason": reason or "none",
                    "duration_seconds": duration.total_seconds(),
                },
                capture_analytics=False,
            )
        except Exception as e:
            workflow.logger.warning(
                "sandbox_deadline_report_failed",
                extra={"run_id": self.context.run_id, "outcome": outcome, "error": str(e)},
            )

    async def _emit_progress(
        self,
        step: str,
        status: str,
        label: str,
        group: str,
        detail: Optional[str] = None,
    ) -> None:
        """Emit a structured progress notification. Best-effort.

        The caller-supplied `group` is scoped with the workflow's run id so
        cards never collide across workflow executions (retries, resumes). The
        scoped id is what actually goes on the wire — callers don't need to
        think about uniqueness.
        """
        scoped_group = f"{group}:{self.context.run_id}"
        try:
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
        except Exception as e:
            workflow.logger.warning(
                "emit_progress_failed",
                extra={
                    "run_id": self.context.run_id,
                    "step": step,
                    "status": status,
                    "error": str(e),
                },
            )

    async def _update_task_run_status(
        self,
        status: str,
        error_message: Optional[str] = None,
        run_id: Optional[str] = None,
        timed_out_inactivity: bool = False,
        error_type: Optional[str] = None,
        timeout_marker: Optional[str] = None,
    ) -> None:
        seconds_since_last_agent_heartbeat = (
            (workflow.now() - self._last_agent_heartbeat_at).total_seconds() if self._last_agent_heartbeat_at else None
        )
        await workflow.execute_activity(
            update_task_run_status,
            UpdateTaskRunStatusInput(
                run_id=run_id if run_id is not None else self.context.run_id,
                status=status,
                error_message=error_message,
                timed_out_inactivity=timed_out_inactivity,
                error_type=error_type,
                timeout_marker=timeout_marker,
                agent_active_at_termination=self._agent_active,
                end_of_turn_received=self._end_of_turn_received,
                last_agent_heartbeat_at=(
                    self._last_agent_heartbeat_at.isoformat() if self._last_agent_heartbeat_at else None
                ),
                seconds_since_last_agent_heartbeat=seconds_since_last_agent_heartbeat,
            ),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _run_credential_refresh_until_sandbox_gone(self, sandbox_id: str) -> None:
        exit_reason = await run_credential_refresh_loop(self.context, sandbox_id)
        if exit_reason == CredentialRefreshExitReason.SANDBOX_GONE:
            workflow.logger.warning(
                "sandbox_gone_detected",
                extra={"run_id": self.context.run_id, "sandbox_id": sandbox_id},
            )
            self._sandbox_gone = True
        elif exit_reason == CredentialRefreshExitReason.CREDENTIALS_UNAVAILABLE:
            workflow.logger.warning(
                "credential_refresh_stopped_credentials_unavailable",
                extra={"run_id": self.context.run_id, "sandbox_id": sandbox_id},
            )
        elif exit_reason == CredentialRefreshExitReason.TASK_GONE:
            workflow.logger.warning(
                "task_rows_gone_detected",
                extra={"run_id": self.context.run_id, "sandbox_id": sandbox_id},
            )
            # Ends the main loop through the sandbox-gone event; the status update on that
            # path then fails non-retryably (the rows are gone), failing the workflow instead
            # of leaving it waiting on signals that can never arrive.
            self._sandbox_gone = True

    def _onboarding_exit_is_failure(self) -> bool:
        """Whether a non-signal exit should terminalize an onboarding run as FAILED.

        Onboarding runs are one-shot: nobody resumes them, so a run that stopped without
        delivering anything is a failed setup and must read as one. A run that already
        opened its PR did deliver, and the wizard keys its success headline and PR CTA off
        the terminal status, so downgrading that run would report a failed install over a
        perfectly good PR. Other origins keep completing either way, because their resume
        flows treat the stopped run as the resumable snapshot.

        `_pr_progress_emitted` only ever flips inside the CI follow-up loop's `get_pr_context`
        call, so a false latch means "no PR" only once that loop has actually looked. A run
        whose loop never ran (disabled for the org, or the exit landed inside the first
        `CI_FOLLOW_UP_DELAY`) has no observation either way, and downgrading on the unobserved
        latch would report a failed install over a PR sitting on the user's repo. Requiring a
        completed follow-up round makes the downgrade evidence-based; a run that never intended
        to open a PR needs no observation, since there is nothing for it to have delivered.
        """
        if self.context.origin_product != _ONBOARDING_ORIGIN_PRODUCT or not _run_lifecycle_bounds_enabled():
            return False
        if self._pr_progress_emitted:
            return False
        return not self.context.create_pr or self._ci_repetitions > 0

    def _mark_sandbox_gone(self) -> None:
        # A sandbox that vanished mid-setup is a failed setup for onboarding; see
        # _onboarding_exit_is_failure for why a run that already opened its PR is exempt.
        self._completion_status = "failed" if self._onboarding_exit_is_failure() else "completed"
        self._completion_error = SANDBOX_GONE_ERROR_MESSAGE
        self._completion_timeout_marker = SANDBOX_GONE_STATE_KEY
        self._task_completed = True

    async def _rotate_sandbox_before_deadline(
        self,
        old_sandbox_id: str,
        relay_task: asyncio.Task[None] | None,
        credential_refresh_task: asyncio.Task[None] | None,
    ) -> SandboxRotation:
        """Move the run onto a replacement sandbox built from a snapshot of the current one.

        Every failure leaves the run on the sandbox it already had, which still has the lead
        time left on its clock — a better place to be than half-way onto a replacement.

        Both background tasks are bound to one sandbox and have to move with it. The credential
        refresh loop is the sharper of the two: left watching the old sandbox, it reads the
        cleanup below as SANDBOX_GONE and ends a run that is now healthy on the replacement.

        Clients never hold the sandbox URL — they read the run's Redis stream through Django and
        send commands the same way — so the swap needs no client involvement beyond keeping that
        stream fed.
        """
        self._resume_snapshot_invalidated = False
        snapshot = await self._create_resume_snapshot_output(old_sandbox_id, reason="ttl_rotation", allow_pruning=False)
        if snapshot is None or not snapshot.external_id:
            return SandboxRotation(
                relay_task=relay_task, credential_refresh_task=credential_refresh_task, reason="snapshot_missing"
            )

        self.context.state = {
            **(self.context.state or {}),
            "snapshot_external_id": snapshot.external_id,
            "snapshot_kind": snapshot.snapshot_kind,
            "snapshot_mount_path": snapshot.snapshot_mount_path,
            "same_run_resume": True,
            "same_run_resume_idle": True,
        }
        live_sandbox = PreRotationSandbox(
            sandbox_id=old_sandbox_id,
            sandbox_url=self._sandbox_url,
            connect_token=self._sandbox_connect_token,
            jwt_kid=self._sandbox_jwt_kid,
            ttl_expires_at=self._sandbox_ttl_expires_at,
            ttl_snapshot_taken=self._sandbox_ttl_snapshot_taken,
        )

        if relay_task is not None:
            await self._cancel_relay(relay_task)
            relay_task = None
        if credential_refresh_task is not None:
            await self._cancel_relay(credential_refresh_task)
            credential_refresh_task = None

        try:
            sandbox_output = await self._get_sandbox_for_repository()
            await self._start_agent_server(sandbox_output)
        except Exception as e:
            workflow.logger.warning(
                "sandbox_rotation_failed",
                extra={
                    "run_id": self.context.run_id,
                    "sandbox_id": old_sandbox_id,
                    "error": str(e),
                    **self._activity_error_properties(e),
                },
            )
            return await self._abandon_rotation(live_sandbox, reason="provision_failed")

        if not sandbox_output.used_snapshot:
            # Provisioning reports success for a replacement it had to build without the
            # snapshot — a dead restore it fell back from, or a provider-side downgrade. That
            # sandbox holds the branch head, not the run's working tree, so completing the
            # rotation would destroy the only copy of the agent's uncommitted work and then
            # tell the user the session carried over.
            workflow.logger.warning(
                "sandbox_rotation_abandoned_without_snapshot",
                extra={
                    "run_id": self.context.run_id,
                    "sandbox_id": old_sandbox_id,
                    "replacement_sandbox_id": sandbox_output.sandbox_id,
                },
            )
            return await self._abandon_rotation(live_sandbox, reason="snapshot_unused")

        self._sandbox_url = sandbox_output.sandbox_url
        self._sandbox_connect_token = sandbox_output.connect_token
        self._sandbox_jwt_kid = sandbox_output.jwt_kid
        self._sandbox_id_for_cleanup = sandbox_output.sandbox_id
        relay_task = self._spawn_event_relay(
            sandbox_output.sandbox_url, sandbox_output.connect_token, sandbox_output.sandbox_id
        )
        credential_refresh_task = self._spawn_credential_refresh(sandbox_output.sandbox_id)
        await self._cleanup_sandbox(old_sandbox_id, complete_stream=False)
        workflow.logger.info(
            "sandbox_rotated",
            extra={
                "run_id": self.context.run_id,
                "previous_sandbox_id": old_sandbox_id,
                "sandbox_id": sandbox_output.sandbox_id,
                "used_snapshot": sandbox_output.used_snapshot,
            },
        )
        return SandboxRotation(
            sandbox_id=sandbox_output.sandbox_id,
            relay_task=relay_task,
            credential_refresh_task=credential_refresh_task,
            snapshot_saved=True,
        )

    async def _abandon_rotation(self, live: PreRotationSandbox, *, reason: str) -> SandboxRotation:
        """Back out of a rotation and put the run back on the sandbox it already had.

        Provisioning publishes the replacement's connection details as soon as that sandbox
        exists, so backing out means tearing it down and pointing the run's persisted routing,
        event relay and credential refresh loop at the original again.
        """
        abandoned = self._sandbox_id_for_cleanup
        routing_restored = True
        if abandoned and abandoned != live.sandbox_id:
            await self._cleanup_sandbox(abandoned, complete_stream=False)
            if live.sandbox_url:
                routing_restored = await self._restore_sandbox_connection_state(
                    live.sandbox_id, live.sandbox_url, live.connect_token, live.jwt_kid
                )
        self._sandbox_id_for_cleanup = live.sandbox_id
        self._sandbox_jwt_kid = live.jwt_kid
        self._sandbox_ttl_expires_at = live.ttl_expires_at
        self._sandbox_ttl_snapshot_taken = live.ttl_snapshot_taken
        relay_task = (
            self._spawn_event_relay(live.sandbox_url, live.connect_token, live.sandbox_id) if live.sandbox_url else None
        )
        return SandboxRotation(
            relay_task=relay_task,
            credential_refresh_task=self._spawn_credential_refresh(live.sandbox_id),
            routing_restored=routing_restored,
            snapshot_saved=not self._resume_snapshot_invalidated,
            reason=reason,
        )

    def _spawn_credential_refresh(self, sandbox_id: str) -> asyncio.Task[None] | None:
        if not self.context.has_github_credentials:
            return None
        return asyncio.ensure_future(self._run_credential_refresh_until_sandbox_gone(sandbox_id))

    async def _restore_sandbox_connection_state(
        self, sandbox_id: str, sandbox_url: str, connect_token: str | None, jwt_kid: str | None
    ) -> bool:
        try:
            await workflow.execute_activity(
                restore_sandbox_connection_state,
                RestoreSandboxConnectionStateInput(
                    run_id=self.context.run_id,
                    sandbox_id=sandbox_id,
                    sandbox_url=sandbox_url,
                    connect_token=connect_token,
                    jwt_kid=jwt_kid,
                ),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except Exception as e:
            workflow.logger.exception(
                "restore_sandbox_connection_state_failed",
                extra={"run_id": self.context.run_id, "sandbox_id": sandbox_id, "error": str(e)},
            )
            return False
        return True

    def _spawn_event_relay(
        self, sandbox_url: str, connect_token: str | None, sandbox_id: str | None
    ) -> asyncio.Task[None] | None:
        """Start whichever event pump this run needs, or None when the sandbox posts its own
        events and nothing has to tail them.

        Sequenced ingest streams events straight to Redis, bypassing the SSE relay that normally
        fans out the Slack agent-design signals, so that case tails the Redis stream instead.
        """
        if not self.context.sandbox_event_ingest_enabled:
            return asyncio.ensure_future(self._relay_sandbox_events(sandbox_url, connect_token, sandbox_id=sandbox_id))
        if self._is_agent_design_enabled:
            return asyncio.ensure_future(self._relay_agent_design_signals())
        return None

    async def _relay_sandbox_events(
        self, sandbox_url: str, connect_token: str | None, sandbox_id: str | None = None
    ) -> None:
        """Start the SSE relay activity as a concurrent task (best-effort)."""
        try:
            relay_input = RelaySandboxEventsInput(
                run_id=self.context.run_id,
                task_id=self.context.task_id,
                sandbox_url=sandbox_url,
                sandbox_connect_token=connect_token,
                team_id=self.context.team_id,
                distinct_id=self.context.distinct_id,
                sandbox_id=sandbox_id,
                slack_thread_context=self._slack_thread_context,
                is_agent_design_enabled=self._is_agent_design_enabled,
            )
            relay_activity = (
                relay_sandbox_events_deferred_completion if _defer_run_stream_completion() else relay_sandbox_events
            )
            sandbox_gone = await workflow.execute_activity(
                relay_activity,
                relay_input,
                start_to_close_timeout=RELAY_SANDBOX_EVENTS_START_TO_CLOSE_TIMEOUT,
                schedule_to_close_timeout=RELAY_SANDBOX_EVENTS_START_TO_CLOSE_TIMEOUT,
                heartbeat_timeout=timedelta(minutes=2),
                # A worker restart (deploy, eviction) kills the in-flight attempt while
                # the sandbox agent keeps working — without retries the event stream is
                # orphaned for good and the run looks dead to the user. Retrying is safe:
                # the agent server buffers events while no relay is attached and replays
                # them on reconnect. Terminal conditions (sandbox gone, reconnect budget
                # exhausted) return cleanly, and application-level failures that write an
                # error sentinel to the stream raise non-retryable ApplicationError, so
                # retries only cover attempt-level deaths where no sentinel was written;
                # schedule_to_close bounds the total.
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=5),
                    maximum_interval=timedelta(minutes=1),
                    maximum_attempts=0,
                    non_retryable_error_types=["ValueError"],
                ),
                cancellation_type=workflow.ActivityCancellationType.TRY_CANCEL,
            )
            if sandbox_gone is True and not self._task_completed:
                workflow.logger.warning(
                    "relay_sandbox_events_reported_sandbox_gone",
                    extra={"run_id": self.context.run_id},
                )
                self._sandbox_gone = True
        except asyncio.CancelledError:
            raise
        except Exception as e:
            workflow.logger.warning(
                "relay_sandbox_events_failed_non_fatal",
                extra={
                    "run_id": self.context.run_id,
                    "error": str(e),
                },
            )

    async def _relay_agent_design_signals(self) -> None:
        """Tail the ingest-populated Redis stream to fan out Slack agent-design signals.

        The flag-on counterpart to ``_relay_sandbox_events``: it reads events from Redis
        rather than the sandbox SSE stream, so it holds no sandbox connection."""
        try:
            relay_input = RelayAgentDesignSignalsInput(
                run_id=self.context.run_id,
                task_id=self.context.task_id,
                slack_thread_context=self._slack_thread_context,
            )
            await workflow.execute_activity(
                relay_agent_design_signals,
                relay_input,
                start_to_close_timeout=RELAY_SANDBOX_EVENTS_START_TO_CLOSE_TIMEOUT,
                schedule_to_close_timeout=RELAY_SANDBOX_EVENTS_START_TO_CLOSE_TIMEOUT,
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=5),
                    maximum_interval=timedelta(minutes=1),
                    maximum_attempts=0,
                    non_retryable_error_types=["ValueError"],
                ),
                cancellation_type=workflow.ActivityCancellationType.TRY_CANCEL,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            workflow.logger.warning(
                "relay_agent_design_signals_failed_non_fatal",
                extra={
                    "run_id": self.context.run_id,
                    "error": str(e),
                },
            )

    @staticmethod
    async def _cancel_relay(relay_task: "asyncio.Task[None]") -> None:
        """Cancel the relay task if still running."""
        if relay_task.done():
            return
        relay_task.cancel()
        try:
            await relay_task
        except (asyncio.CancelledError, Exception):
            pass

    async def _create_resume_snapshot(self, sandbox_id: str, *, reason: str, allow_pruning: bool) -> bool:
        result = await self._create_resume_snapshot_output(sandbox_id, reason=reason, allow_pruning=allow_pruning)
        return bool(result and result.external_id)

    async def _create_resume_snapshot_output(
        self, sandbox_id: str, *, reason: str, allow_pruning: bool
    ) -> CreateResumeSnapshotOutput | None:
        """Create a snapshot for interactive sandbox resume. None when the activity itself failed."""
        try:
            result = await workflow.execute_activity(
                create_resume_snapshot,
                CreateResumeSnapshotInput(
                    sandbox_id=sandbox_id,
                    run_id=self.context.run_id,
                    reason=reason,
                    allow_pruning=allow_pruning,
                ),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            if result.external_id:
                workflow.logger.info(
                    "resume_snapshot_created",
                    extra={
                        "run_id": self.context.run_id,
                        "sandbox_id": sandbox_id,
                        "reason": reason,
                        "snapshot_external_id": result.external_id,
                        "snapshot_kind": result.snapshot_kind,
                        "duration_ms": result.duration_ms,
                    },
                )
                return result
            elif result.error:
                workflow.logger.warning(
                    "resume_snapshot_skipped",
                    extra={
                        "run_id": self.context.run_id,
                        "sandbox_id": sandbox_id,
                        "reason": reason,
                        "snapshot_kind": result.snapshot_kind,
                        "duration_ms": result.duration_ms,
                        "error": result.error,
                    },
                )
                return result
        except Exception as e:
            workflow.logger.warning(
                "resume_snapshot_failed_non_fatal",
                extra={
                    "run_id": self.context.run_id,
                    "sandbox_id": sandbox_id,
                    "reason": reason,
                    "error": str(e),
                },
            )
            return None
        return result

    async def _trigger_snapshot_workflow(self) -> None:
        github_integration_id = self.context.github_integration_id
        repository = self.context.repository
        if github_integration_id is None or repository is None:
            workflow.logger.info("Skipping snapshot workflow — no repository configured")
            return

        workflow_id = f"create-snapshot-for-repository-{github_integration_id}-{repository.replace('/', '-')}"

        await workflow.start_child_workflow(
            workflow="create-snapshot-for-repository",
            arg=CreateSnapshotForRepositoryInput(
                github_integration_id=github_integration_id,
                repository=repository,
                team_id=self.context.team_id,
            ),
            id=workflow_id,
            task_queue=settings.TASKS_TASK_QUEUE,
            parent_close_policy=ParentClosePolicy.ABANDON,  # This will allow the snapshot workflow to continue even if the task workflow fails or closes
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

    async def _post_slack_update(self, sandbox_cleaned: bool = False) -> None:
        if not self._slack_thread_context:
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

    async def _resolve_agent_design_flag(self) -> bool:
        if not self._slack_thread_context:
            return False
        integration_id = self._slack_thread_context.get("integration_id")
        if not integration_id:
            return False
        try:
            return await workflow.execute_activity(
                is_slack_app_agent_design_enabled_for_task_activity,
                IsSlackAppAgentDesignEnabledForTaskActivityInput(
                    integration_id=int(integration_id),
                    run_id=self.context.run_id,
                ),
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except Exception:
            # Fail closed.
            workflow.logger.warning("slack_app_agent_design_flag_eval_failed", extra={"run_id": self.context.run_id})
            return False

    @temporalio.workflow.signal
    async def complete_task(self, status: str = "completed", error_message: Optional[str] = None) -> None:
        self._completion_status = status
        self._completion_error = error_message
        # Completion signals come from the agent reporting its own terminal state
        # through the run PATCH endpoint (which flips the row first, so the status
        # activity usually sees no transition and skips its capture).
        self._completion_error_type = "agent_reported" if status == "failed" else None
        self._task_completed = True

    # ─── Slack agent-design streaming ─── (per-turn signals from relay_sandbox_events)

    @temporalio.workflow.signal
    async def turn_started(self, payload: dict[str, Any]) -> None:
        if not self._is_agent_design_enabled:
            return
        # Any orphaned previous-turn child times out on its own.
        slack_ctx = payload.get("slack_thread_context") or self._slack_thread_context or {}
        if not slack_ctx:
            return
        relay_workflow_id = f"slack-agent-design-relay-{self.context.run_id}-{workflow.uuid4()}"
        self._current_slack_relay_workflow_id = relay_workflow_id
        await workflow.start_child_workflow(
            SlackAgentDesignRelayWorkflow.run,
            SlackAgentDesignRelayInput(slack_thread_context=slack_ctx, run_id=self.context.run_id),
            id=relay_workflow_id,
            task_queue=workflow.info().task_queue,
            # Cancel on parent close so the relay's finally block runs
            # stop_slack_agent_design_stream — otherwise the plan-block
            # stream is orphaned until Slack's own GC.
            parent_close_policy=ParentClosePolicy.REQUEST_CANCEL,
            execution_timeout=timedelta(hours=1),
        )

    @temporalio.workflow.signal
    async def agent_status_update(self, payload: dict[str, Any]) -> None:
        """Forward {title, details} step update to the current per-turn child."""
        if not self._is_agent_design_enabled or not self._current_slack_relay_workflow_id:
            return
        try:
            handle = workflow.get_external_workflow_handle(self._current_slack_relay_workflow_id)
            await handle.signal(SlackAgentDesignRelayWorkflow.agent_status_update, payload)
        except Exception as e:
            # Child already gone — drop the update.
            workflow.logger.debug(
                "slack_status_forward_failed",
                extra={"run_id": self.context.run_id, "error": str(e)},
            )

    @temporalio.workflow.signal
    async def agent_text_delta(self, text: str) -> None:
        if not self._is_agent_design_enabled or not self._current_slack_relay_workflow_id:
            return
        try:
            handle = workflow.get_external_workflow_handle(self._current_slack_relay_workflow_id)
            await handle.signal(SlackAgentDesignRelayWorkflow.agent_text_delta, text)
        except Exception as e:
            workflow.logger.debug(
                "slack_text_forward_failed",
                extra={"run_id": self.context.run_id, "error": str(e)},
            )

    @temporalio.workflow.signal
    async def turn_completed(self) -> None:
        if not self._is_agent_design_enabled or not self._current_slack_relay_workflow_id:
            return
        relay_id = self._current_slack_relay_workflow_id
        self._current_slack_relay_workflow_id = None
        try:
            handle = workflow.get_external_workflow_handle(relay_id)
            await handle.signal(SlackAgentDesignRelayWorkflow.complete_turn)
        except Exception as e:
            workflow.logger.debug(
                "slack_status_complete_failed",
                extra={"run_id": self.context.run_id, "error": str(e)},
            )

    @temporalio.workflow.signal
    async def heartbeat(self, agent_active: bool = False) -> None:
        if not agent_active:
            return
        now = workflow.now()
        self._heartbeat_received = True
        self._last_active_time = now
        self._last_agent_heartbeat_at = now

    @temporalio.workflow.signal
    async def client_activity(self) -> None:
        self._client_activity_received = True
        self._last_active_time = workflow.now()

    @temporalio.workflow.signal
    async def agent_state_changed(self, agent_active: bool) -> None:
        self._agent_active = agent_active
        self._end_of_turn_received = not agent_active

    @temporalio.workflow.signal
    async def send_followup_message(
        self,
        message: str | None = None,
        artifact_ids: Optional[list[str]] = None,
        message_id: str | bool | None = None,
        actor_user_id: Optional[int] = None,
        message_context: Optional[dict[str, Any]] = None,
    ) -> None:
        # The third positional field is a message ID for current senders, but
        # replayed steering histories may contain a boolean in that slot.
        legacy_steer = message_id if isinstance(message_id, bool) else False
        stable_message_id = message_id if isinstance(message_id, str) else None
        self._queue_followup_message(
            message,
            artifact_ids,
            actor_user_id=actor_user_id,
            message_id=stable_message_id,
            message_context=message_context,
            steer=legacy_steer,
        )

    @temporalio.workflow.signal(name=SEND_STEER_SIGNAL)
    async def send_steer_message(
        self,
        message: str | None = None,
        artifact_ids: Optional[list[str]] = None,
        message_id: str | None = None,
        actor_user_id: int | None = None,
        message_context: dict[str, Any] | None = None,
    ) -> None:
        self._queue_followup_message(
            message,
            artifact_ids,
            actor_user_id=actor_user_id,
            message_id=message_id,
            message_context=message_context,
            steer=True,
        )

    @temporalio.workflow.query(name=STEERING_PROTOCOL_QUERY)
    def steering_protocol_version(self) -> int:
        return STEERING_PROTOCOL_VERSION

    def _queue_followup_message(
        self,
        message: str | None,
        artifact_ids: Optional[list[str]],
        actor_user_id: int | None = None,
        message_id: str | None = None,
        message_context: dict[str, Any] | None = None,
        *,
        steer: bool,
    ) -> None:
        # Log signal arrival so we can correlate it with the adapter's "begin dispatch"
        # log below — gaps between the two point at workflow-loop backpressure.
        context = self._context
        workflow.logger.info(
            "send_followup_signal_received",
            extra={
                "run_id": context.run_id if context is not None else None,
                "message_length": len(message or ""),
                "artifact_count": len(artifact_ids or []),
            },
        )
        if self._shutting_down:
            workflow.logger.warning(
                "send_followup_signal_rejected_closing",
                extra={"run_id": context.run_id if context is not None else None},
            )
            return
        if message_id:
            dedupe_key = _message_dedupe_key(message_id, actor_user_id, message_context)
            if dedupe_key in self._accepted_message_id_set:
                return
            if len(self._accepted_message_ids) >= MAX_ACCEPTED_MESSAGE_IDS:
                oldest_key = self._accepted_message_ids.pop(0)
                self._accepted_message_id_set.discard(oldest_key)
            self._accepted_message_ids.append(dedupe_key)
            self._accepted_message_id_set.add(dedupe_key)

        pending_followup = PendingFollowup(
            message=message,
            artifact_ids=artifact_ids or [],
            actor_user_id=actor_user_id,
            message_id=message_id,
            context=message_context if isinstance(message_context, dict) else {},
            steer=steer,
            sequence=self._next_followup_sequence,
        )
        self._next_followup_sequence += 1
        # Always queue. `deprecate_patch` accepts existing non-deprecated
        # markers from workflows that ran the prior `workflow.patched(...)`
        # gate, so this is safe to deploy alongside in-flight workflows. The
        # consumption loop in `run()` still drains a stray `_pending_followup`
        # for defense in depth, but new code never sets it.
        workflow.deprecate_patch(_PATCH_ID_FOLLOWUP_QUEUE)
        self._pending_followups.append(pending_followup)

    @temporalio.workflow.signal
    async def send_permission_response(self, response: dict[str, Any]) -> None:
        request_id = response.get("request_id")
        option_id = response.get("option_id")
        actor_user_id = response.get("actor_user_id")
        if not isinstance(request_id, str) or not request_id:
            workflow.logger.warning("permission_response_signal_ignored", extra={"reason": "missing_request_id"})
            return
        if not isinstance(option_id, str) or not option_id:
            workflow.logger.warning(
                "permission_response_signal_ignored",
                extra={"request_id": request_id, "reason": "missing_option_id"},
            )
            return
        if not isinstance(actor_user_id, int) or isinstance(actor_user_id, bool):
            workflow.logger.warning(
                "permission_response_signal_ignored",
                extra={"request_id": request_id, "reason": "missing_actor_user_id"},
            )
            return

        actor_slack_user_id = response.get("actor_slack_user_id")
        denial_message = response.get("denial_message")
        broker_reason = response.get("broker_reason")
        pending_response = PendingPermissionResponse(
            request_id=request_id,
            option_id=option_id,
            actor_user_id=actor_user_id,
            actor_slack_user_id=actor_slack_user_id if isinstance(actor_slack_user_id, str) else None,
            is_denial=bool(response.get("is_denial")),
            denial_message=denial_message if isinstance(denial_message, str) else None,
            broker_reason=broker_reason if isinstance(broker_reason, str) else None,
        )
        self._pending_permission_responses.append(pending_response)
        context = self._context
        workflow.logger.info(
            "permission_response_signal_received",
            extra={
                "run_id": context.run_id if context is not None else None,
                "request_id": request_id,
                "option_id": option_id,
                "actor_user_id": actor_user_id,
                "is_denial": pending_response.is_denial,
            },
        )

    async def _send_followup_to_sandbox(
        self,
        message: str | None,
        artifact_ids: list[str],
        actor_user_id: int | None = None,
        message_id: str | None = None,
        context: dict[str, Any] | None = None,
        *,
        steer: bool = False,
        user_originated: bool = True,
    ) -> str | None:
        workflow.logger.info(
            "send_followup_dispatch_begin",
            extra={
                "run_id": self.context.run_id,
                "message_length": len(message or ""),
                "artifact_count": len(artifact_ids),
            },
        )
        try:
            max_attempts = 1 if self.context.task_runtime == "pi" else SEND_FOLLOWUP_MAX_ATTEMPTS
            return await workflow.execute_activity(
                send_followup_to_sandbox,
                SendFollowupToSandboxInput(
                    run_id=self.context.run_id,
                    message=message,
                    posthog_mcp_scopes=self._posthog_mcp_scopes,
                    artifact_ids=artifact_ids,
                    message_id=message_id or str(workflow.uuid4()),
                    actor_user_id=actor_user_id,
                    context=context,
                    steer=steer,
                    max_attempts=max_attempts,
                ),
                start_to_close_timeout=timedelta(minutes=35),
                heartbeat_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=5),
                    maximum_attempts=max_attempts,
                ),
            )
        except Exception as e:
            error_properties = self._activity_error_properties(e)
            cause_message = error_properties.get("cause_error_message")
            workflow.logger.warning(
                "send_followup_to_sandbox_failed",
                extra={
                    "run_id": self.context.run_id,
                    "error": str(e),
                    **error_properties,
                },
            )
            peer_message_id = peer_message_id_from_context(context)
            if peer_message_id is not None:
                # Peer messages are best-effort: record the outcome on the sender's
                # audit row and leave this (recipient) run's completion state
                # untouched. The branch is replay-safe because pre-feature histories
                # cannot contain peer context.
                if is_timeout_activity_failure(e):
                    # The timed-out attempt may still deliver, so leave the row
                    # non-terminal for a possible delivered write.
                    workflow.logger.warning(
                        "peer_message_delivery_timeout_left_nonterminal",
                        extra={"run_id": self.context.run_id, "peer_message_id": peer_message_id},
                    )
                    return None
                await self._record_peer_message_delivery_failure(peer_message_id, cause_message or str(e))
                return None
            if self.context.mode == "interactive" and workflow.patched(_PATCH_ID_FOLLOWUP_FAILURE_KEEPS_RUN):
                if message_id:
                    dedupe_key = _message_dedupe_key(message_id, actor_user_id, context)
                    if dedupe_key in self._accepted_message_id_set:
                        self._accepted_message_id_set.discard(dedupe_key)
                        self._accepted_message_ids.remove(dedupe_key)
                if user_originated:
                    # A user follow-up can arrive without a message_id, so the card can't hinge on
                    # one; the generated group still gives the user a failure notice instead of a
                    # silently frozen conversation. CI nudges skip it because the copy is user-facing.
                    await self._emit_progress(
                        step="followup_delivery",
                        status="failed",
                        label="Couldn't deliver your message",
                        group=f"followup-delivery:{message_id or workflow.uuid4()}",
                        detail=str(cause_message or e),
                    )
                return None
            self._completion_status = "failed"
            self._completion_error = f"Follow-up delivery failed: {cause_message or e}"
            self._completion_error_type = "followup_delivery_failed"
            self._task_completed = True
        return None

    async def _record_peer_message_delivery_failure(self, peer_message_id: str, detail: str) -> None:
        """Terminalize the peer message row when delivery failed in a way the
        delivery activity could not record itself (worker death, timeout). The
        transition is idempotent (non-terminal rows only), so double-reporting with
        the activity is harmless; a recording failure is logged and swallowed —
        bookkeeping must not take the run down either."""
        try:
            await workflow.execute_activity(
                record_peer_message_outcome,
                RecordPeerMessageOutcomeInput(
                    peer_message_id=peer_message_id,
                    outcome="delivery_failed",
                    failure_phase="sandbox_delivery",
                    failure_detail=truncate_error_message(detail),
                ),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=2),
                    maximum_attempts=3,
                ),
            )
        except Exception:
            workflow.logger.warning(
                "peer_message_failure_record_failed",
                extra={"run_id": self.context.run_id, "peer_message_id": peer_message_id},
            )
