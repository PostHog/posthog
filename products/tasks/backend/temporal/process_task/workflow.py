import json
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Optional

from django.conf import settings

import temporalio
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.workflow import ParentClosePolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.oauth import PosthogMcpScopes

from products.tasks.backend.logic.services.sandbox import is_public_sandbox_repo
from products.tasks.backend.temporal.create_snapshot.workflow import CreateSnapshotForRepositoryInput
from products.tasks.backend.temporal.process_task.activities.get_pr_context import GetPrContextInput, get_pr_context

from .activities.cleanup_sandbox import CleanupSandboxInput, cleanup_sandbox
from .activities.create_resume_snapshot import CreateResumeSnapshotInput, create_resume_snapshot
from .activities.emit_progress_activity import EmitProgressInput, emit_progress_activity
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
from .activities.post_slack_update import PostSlackUpdateInput, post_slack_update
from .activities.provision_sandbox import (
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
from .activities.read_sandbox_logs import ReadSandboxLogsInput, read_sandbox_logs
from .activities.relay_sandbox_events import RelaySandboxEventsInput, relay_sandbox_events
from .activities.run_wizard import RunWizardInput, run_wizard
from .activities.send_followup_to_sandbox import (
    SEND_FOLLOWUP_MAX_ATTEMPTS,
    SendFollowupToSandboxInput,
    send_followup_to_sandbox,
)
from .activities.start_agent_server import (
    MarkRepoReadyInput,
    StartAgentServerInput,
    StartAgentServerOutput,
    await_agent_server_ready,
    launch_agent_server,
    mark_repo_ready,
    start_agent_server,
)
from .activities.track_workflow_event import TrackWorkflowEventInput, track_workflow_event
from .activities.update_task_run_status import UpdateTaskRunStatusInput, update_task_run_status
from .credential_refresh import SANDBOX_GONE_ERROR_MESSAGE, CredentialRefreshExitReason, run_credential_refresh_loop
from .slack_agent_design_relay import SlackAgentDesignRelayInput, SlackAgentDesignRelayWorkflow


@dataclass
class ProcessTaskInput:
    run_id: str
    create_pr: bool = True
    slack_thread_context: Optional[dict[str, Any]] = None
    posthog_mcp_scopes: PosthogMcpScopes = "read_only"
    prewarmed: bool = False


@dataclass
class PendingFollowup:
    message: str | None
    artifact_ids: list[str]


@dataclass
class ProcessTaskOutput:
    success: bool
    task_result: Optional[ExecuteTaskOutput] = None
    error: Optional[str] = None
    sandbox_id: Optional[str] = None


class TaskEvent(StrEnum):
    SIGNAL_RECEIVED = "signal_received"
    TIMEOUT_REACHED = "timeout_reached"
    CI_FOLLOW_UP = "ci_follow_up"
    SANDBOX_GONE = "sandbox_gone"


class CIFollowUpDecision(StrEnum):
    FIRE = "fire"
    SKIP = "skip"
    NO_PR = "no_pr"


# Legacy re-exports kept while process_task is still on the worker. New
# workers should import them directly from `products.tasks.backend.temporal.constants`.
from products.tasks.backend.temporal.constants import (  # noqa: E402
    CI_FOLLOW_UP_DELAY,
    DEFAULT_CI_MESSAGE,
    INACTIVITY_TIMEOUT,
    MAX_CI_REPETITIONS,
    PENDING_MESSAGE_FORWARD_TIMEOUT_SECONDS,
    RELAY_SANDBOX_EVENTS_START_TO_CLOSE_TIMEOUT,
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

# #60923 dropped the redundant slack post that ran immediately after sandbox
# provisioning — between `_get_sandbox_for_repository` and the agent-start
# progress emit. Pre-rollout histories scheduled a `post_slack_update` activity
# at that point, so removing it unconditionally broke replay of in-flight
# workflows with TMPRL1100: the next command (`emit_progress_activity`) no
# longer matched the recorded `post_slack_update` event. Gate the removal —
# post-rollout executions skip the call, replays of older histories still
# schedule it. Same two-step cleanup lifecycle as the patches above.
_PATCH_ID_DROP_SLACK_POST_AFTER_PROVISIONING = "tasks-drop-slack-post-after-provisioning"

# Gates the new agent-design flag-eval execute_activity site.
# Two-step deprecate-then-delete cleanup lifecycle as above.
_PATCH_ID_SLACK_AGENT_DESIGN_STATUS = "tasks-slack-agent-design-status"

# Gates the refusal to execute local-environment (desktop-driven) runs. Pre-guard
# histories of such runs proceeded into provisioning; the marker keeps their replays
# deterministic. Same two-step cleanup lifecycle as above.
_PATCH_ID_SKIP_LOCAL_ENVIRONMENT_RUNS = "tasks-skip-local-environment-runs"


def _deprecate_ci_follow_up_pr_context_patch() -> None:
    workflow.deprecate_patch(_PATCH_ID_CI_FOLLOW_UP_PR_CONTEXT)


@temporalio.workflow.defn(name="process-task")
class ProcessTaskWorkflow(PostHogWorkflow):
    def __init__(self) -> None:
        self._context: Optional[TaskProcessingContext] = None
        self._slack_thread_context: Optional[dict[str, Any]] = None
        self._posthog_mcp_scopes: PosthogMcpScopes = "read_only"
        self._sandbox_id_for_cleanup: Optional[str] = None
        self._task_completed: bool = False
        self._completion_status: str = "completed"
        self._completion_error: Optional[str] = None
        self._heartbeat_received: bool = False
        self._prewarmed: bool = False
        self._first_user_message_received: bool = False
        self._sandbox_gone: bool = False
        self._pending_followup: PendingFollowup | None = None
        self._pending_followups: list[PendingFollowup] = []
        self._ci_repetitions: int = 0
        self._last_active_time: Optional[datetime] = None
        # Tracks which progress step is currently in-progress (step, label,
        # group) so we can emit a "failed" transition from the workflow-level
        # exception handler onto the right card.
        self._current_progress_step: Optional[tuple[str, str, str]] = None
        self._pr_fingerprint: Optional[str] = None
        # Emit the "PR opened / keeping CI green" progress once, the first time we observe a PR — the
        # agent opens it mid-run and then keeps it green, so without this the UI dead-ends at "Started agent".
        self._pr_progress_emitted: bool = False
        # Decided once at workflow start; gates the placeholder skip + relay spawn.
        self._is_agent_design_enabled: bool = False
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
        return ProcessTaskInput(
            run_id=loaded["run_id"],
            create_pr=loaded.get("create_pr", True),
            slack_thread_context=loaded.get("slack_thread_context"),
            posthog_mcp_scopes=loaded.get("posthog_mcp_scopes", "read_only"),
            prewarmed=loaded.get("prewarmed", False),
        )

    async def _wait_for_task_external_event(self):
        await workflow.wait_condition(
            lambda: (
                self._task_completed
                or self._sandbox_gone
                or self._heartbeat_received
                or self._pending_followup is not None
                or len(self._pending_followups) > 0
            )
        )
        if self._sandbox_gone and not self._task_completed:
            return TaskEvent.SANDBOX_GONE
        return TaskEvent.SIGNAL_RECEIVED

    async def _wait_for_inactivity(self, timeout: timedelta = INACTIVITY_TIMEOUT):
        await workflow.sleep(timeout.total_seconds())
        return TaskEvent.TIMEOUT_REACHED

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
        if ci_follow_up_scheduled:
            possible_events.append(asyncio.create_task(self._wait_for_ci_follow_up()))
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
        # First time we observe a PR: surface "Opened pull request" + "Keeping CI green" so the UI moves
        # past "Started agent". The url rides the "pr" step's detail; the frontend turns it into the CTA.
        if pr_context.pr_url and not self._pr_progress_emitted:
            self._pr_progress_emitted = True
            await self._emit_progress("pr", "completed", "Opened pull request", "setup", detail=pr_context.pr_url)
            await self._emit_progress("ci", "in_progress", "Keeping CI green", "setup")
        if pr_context.pr_state == "closed":
            workflow.logger.info(
                "PR is closed, skipping CI follow-up",
                extra={
                    "run_id": self.context.run_id,
                    "pr_url": pr_context.pr_url,
                    "pr_state": pr_context.pr_state,
                },
            )
            return CIFollowUpDecision.SKIP
        if self._pr_fingerprint != pr_context.fingerprint:
            workflow.logger.info(
                "PR context has changed, running CI follow-up",
                extra={
                    "run_id": self.context.run_id,
                    "pr_url": pr_context.pr_url,
                    "pr_state": pr_context.pr_state,
                },
            )
            self._pr_fingerprint = pr_context.fingerprint
            return CIFollowUpDecision.FIRE
        else:
            workflow.logger.info(
                "PR context has not changed, skipping CI follow-up",
                extra={
                    "run_id": self.context.run_id,
                    "pr_url": pr_context.pr_url,
                    "pr_state": pr_context.pr_state,
                },
            )
            return CIFollowUpDecision.SKIP

    async def _dispatch_ci_follow_up(self) -> None:
        self._ci_repetitions += 1
        ci_message = self.context.ci_prompt or DEFAULT_CI_MESSAGE
        self._last_active_time = workflow.now()
        await self._send_followup_to_sandbox(ci_message, [])

    @workflow.run
    async def run(self, input: ProcessTaskInput) -> ProcessTaskOutput:
        sandbox_id = None
        sandbox_cleaned = False
        timed_out = False
        run_id = input.run_id
        self._sandbox_id_for_cleanup = None
        self._slack_thread_context = input.slack_thread_context
        self._prewarmed = input.prewarmed
        credential_refresh_task: asyncio.Task[None] | None = None
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
            await self._run_wizard_if_configured(sandbox_output)

            # Start agent-server for direct connection from PostHog Code
            if sandbox_output.agent_server_launched:
                agent_server_output = await self._await_agent_server_ready(sandbox_output)
            else:
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

            relay_task: asyncio.Task[None] | None = None
            if not self.context.sandbox_event_ingest_enabled:
                relay_task = asyncio.ensure_future(
                    self._relay_sandbox_events(agent_server_output, sandbox_id=sandbox_id)
                )

            if self.context.has_github_credentials:
                credential_refresh_task = asyncio.ensure_future(
                    self._run_credential_refresh_until_sandbox_gone(sandbox_id)
                )

            if self._should_forward_pending_user_message():
                await self._forward_pending_user_message()

            # Wait for completion signal or inactivity timeout.
            # Heartbeat signals reset the inactivity timer, keeping the workflow alive
            # as long as the agent is actively producing logs.
            while not self._task_completed:
                event = await self._wait_for_event()
                match event:
                    case TaskEvent.TIMEOUT_REACHED:
                        timed_out = True
                        break
                    case TaskEvent.CI_FOLLOW_UP:
                        workflow.logger.info(
                            "CI follow-up event triggered",
                            extra={"run_id": self.context.run_id, "repetitions": self._ci_repetitions},
                        )
                        _deprecate_ci_follow_up_pr_context_patch()
                        follow_up_result = await self._should_run_ci_follow_up()
                        match follow_up_result:
                            case CIFollowUpDecision.FIRE:
                                workflow.set_current_details("🔁 Re-checking the PR's CI and nudging the agent.")
                                await self._dispatch_ci_follow_up()
                            case CIFollowUpDecision.NO_PR:
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
                    case TaskEvent.SANDBOX_GONE:
                        self._mark_sandbox_gone()
                    case TaskEvent.SIGNAL_RECEIVED:
                        pending_followup_count = len(self._pending_followups) + (
                            1 if self._pending_followup is not None else 0
                        )
                        if pending_followup_count > 0:
                            workflow.logger.info(
                                "Pending follow-up message received, sending to sandbox",
                                extra={
                                    "run_id": self.context.run_id,
                                    "pending_followup_count": pending_followup_count,
                                },
                            )
                            if self._pending_followup is not None:
                                pending_followup = self._pending_followup
                                self._pending_followup = None
                            else:
                                pending_followup = self._pending_followups.pop(0)
                            self._last_active_time = workflow.now()
                            self._first_user_message_received = True
                            message = pending_followup.message
                            artifact_ids = pending_followup.artifact_ids
                            if self._should_skip_followup(message, artifact_ids):
                                workflow.logger.warning(
                                    "empty_followup_skipped",
                                    extra={"run_id": self.context.run_id},
                                )
                                continue

                            await self._send_followup_to_sandbox(
                                message=message,
                                artifact_ids=artifact_ids,
                            )
                            continue

                        if self._heartbeat_received and not self._task_completed:
                            workflow.logger.info(
                                "Heartbeat received, resetting inactivity timer",
                                extra={"run_id": self.context.run_id},
                            )
                            self._heartbeat_received = False
                            continue
                    case _:
                        raise ValueError(f"Unknown event type: {event}")

            # Cancel background loops as soon as the run ends, not just in `finally` —
            # a hang in the cleanup path below must not leave credential refresh running.
            if relay_task is not None:
                await self._cancel_relay(relay_task)
            if credential_refresh_task is not None:
                await self._cancel_relay(credential_refresh_task)
                credential_refresh_task = None

            if self._task_completed:
                await self._update_task_run_status(self._completion_status, error_message=self._completion_error)
            elif timed_out:
                await self._update_task_run_status("completed", error_message="Run timed out due to inactivity")

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
                await self._cleanup_sandbox(current_sandbox_id)
                sandbox_id = None
                self._sandbox_id_for_cleanup = None
            raise

        except Exception as e:
            current_sandbox_id = sandbox_id or self._sandbox_id_for_cleanup
            error_message = str(e)[:500]
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
            if self._context:
                await self._post_slack_update()

            return ProcessTaskOutput(
                success=False,
                task_result=None,
                error=error_message,
                sandbox_id=current_sandbox_id,
            )

        finally:
            if credential_refresh_task is not None:
                await self._cancel_relay(credential_refresh_task)

            cleanup_sandbox_id = sandbox_id or self._sandbox_id_for_cleanup
            if cleanup_sandbox_id:
                if self._context and self._context.mode == "interactive" and self._context.use_modal_resume_snapshots:
                    await self._create_resume_snapshot(cleanup_sandbox_id)

                await self._read_sandbox_logs(cleanup_sandbox_id)
                await self._cleanup_sandbox(cleanup_sandbox_id)
                sandbox_cleaned = True
                self._sandbox_id_for_cleanup = None

            if sandbox_cleaned and self._slack_thread_context and self._context:
                await self._post_slack_update(sandbox_cleaned=True)

    async def _get_task_processing_context(self, input: ProcessTaskInput) -> TaskProcessingContext:
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

        will_clone = bool(prepared.repository and not used_snapshot and has_clone_credentials)
        will_checkout = bool(prepared.repository and prepared.branch and has_clone_credentials)

        overlap = bool(self.context.overlap_clone_boot_enabled and will_clone)
        if overlap:
            await self._emit_progress("agent", "in_progress", "Starting agent", "setup")
            await self._launch_agent_server(created, defer_for_clone=True)

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
                    used_snapshot=used_snapshot,
                ),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            await self._emit_progress("checkout", "completed", branch_label_done, "setup")

        if overlap:
            await self._mark_repo_ready(created.sandbox_id)

        return GetSandboxForRepositoryOutput(
            sandbox_id=created.sandbox_id,
            sandbox_url=created.sandbox_url,
            connect_token=created.connect_token,
            used_snapshot=used_snapshot,
            should_create_snapshot=not used_snapshot,
            agent_server_launched=overlap,
        )

    async def _cleanup_sandbox(self, sandbox_id: str) -> None:
        context = self._context
        cleanup_input = CleanupSandboxInput(
            sandbox_id=sandbox_id,
            run_id=context.run_id if context else None,
            complete_stream_on_cleanup=bool(context and context.sandbox_event_ingest_enabled),
        )
        await workflow.execute_activity(
            cleanup_sandbox,
            cleanup_input,
            start_to_close_timeout=timedelta(minutes=5),
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

    async def _run_wizard_if_configured(self, sandbox_output: GetSandboxForRepositoryOutput) -> None:
        """Run the setup wizard in the sandbox before the agent, for cloud wizard runs only.

        Fails the run on a non-zero wizard exit (maximum_attempts=1, and the wizard is non-idempotent
        once it has modified files), rather than handing a half-integrated tree to the agent.
        """
        repository = self.context.repository
        # `is not None` (not truthiness): an empty config dict still means "this is a wizard run".
        if self.context.wizard_config is None or not repository:
            return

        await self._emit_progress("wizard", "in_progress", "Running PostHog setup wizard", "setup")
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
        await self._emit_progress("wizard", "completed", "Ran PostHog setup wizard", "setup")

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

    async def _launch_agent_server(
        self, created: GetSandboxForRepositoryOutput, *, defer_for_clone: bool
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
            ),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _mark_repo_ready(self, sandbox_id: str) -> None:
        await workflow.execute_activity(
            mark_repo_ready,
            MarkRepoReadyInput(sandbox_id=sandbox_id, run_id=self.context.run_id),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _await_agent_server_ready(self, sandbox_output: GetSandboxForRepositoryOutput) -> StartAgentServerOutput:
        return await workflow.execute_activity(
            await_agent_server_ready,
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
        track_input = TrackWorkflowEventInput(
            event_name=event_name,
            distinct_id=self.context.distinct_id,
            properties=properties,
            groups={
                "organization": self.context.organization_id,
                "project": self.context.team_uuid,
            },
        )
        await workflow.execute_activity(
            track_workflow_event,
            track_input,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=1),
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
        self, status: str, error_message: Optional[str] = None, run_id: Optional[str] = None
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

    async def _run_credential_refresh_until_sandbox_gone(self, sandbox_id: str) -> None:
        exit_reason = await run_credential_refresh_loop(self.context, sandbox_id)
        if exit_reason == CredentialRefreshExitReason.SANDBOX_GONE:
            workflow.logger.warning(
                "sandbox_gone_detected",
                extra={"run_id": self.context.run_id, "sandbox_id": sandbox_id},
            )
            self._sandbox_gone = True

    def _mark_sandbox_gone(self) -> None:
        self._completion_status = "completed"
        self._completion_error = SANDBOX_GONE_ERROR_MESSAGE
        self._task_completed = True

    async def _relay_sandbox_events(
        self, agent_server_output: StartAgentServerOutput, sandbox_id: str | None = None
    ) -> None:
        """Start the SSE relay activity as a concurrent task (best-effort)."""
        try:
            relay_input = RelaySandboxEventsInput(
                run_id=self.context.run_id,
                task_id=self.context.task_id,
                sandbox_url=agent_server_output.sandbox_url,
                sandbox_connect_token=agent_server_output.connect_token,
                team_id=self.context.team_id,
                distinct_id=self.context.distinct_id,
                sandbox_id=sandbox_id,
                slack_thread_context=self._slack_thread_context,
                is_agent_design_enabled=self._is_agent_design_enabled,
            )
            await workflow.execute_activity(
                relay_sandbox_events,
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

    async def _create_resume_snapshot(self, sandbox_id: str) -> None:
        """Create a snapshot for interactive sandbox resume."""
        try:
            result = await workflow.execute_activity(
                create_resume_snapshot,
                CreateResumeSnapshotInput(
                    sandbox_id=sandbox_id,
                    run_id=self.context.run_id,
                    use_directory_snapshot=self.context.use_modal_directory_resume_snapshots,
                ),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            if result.external_id:
                workflow.logger.info(f"Resume snapshot created: {result.external_id} for sandbox {sandbox_id}")
            elif result.error:
                workflow.logger.warning(f"Resume snapshot skipped: {result.error}")
        except Exception as e:
            workflow.logger.warning(f"Resume snapshot failed (non-fatal): {e}")

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
            SlackAgentDesignRelayInput(slack_thread_context=slack_ctx),
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
        self._heartbeat_received = True
        self._last_active_time = workflow.now()

    @temporalio.workflow.signal
    async def send_followup_message(self, message: str | None = None, artifact_ids: Optional[list[str]] = None) -> None:
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
        pending_followup = PendingFollowup(message=message, artifact_ids=artifact_ids or [])
        # Always queue. `deprecate_patch` accepts existing non-deprecated
        # markers from workflows that ran the prior `workflow.patched(...)`
        # gate, so this is safe to deploy alongside in-flight workflows. The
        # consumption loop in `run()` still drains a stray `_pending_followup`
        # for defense in depth, but new code never sets it.
        workflow.deprecate_patch(_PATCH_ID_FOLLOWUP_QUEUE)
        self._pending_followups.append(pending_followup)

    async def _send_followup_to_sandbox(self, message: str | None, artifact_ids: list[str]) -> None:
        workflow.logger.info(
            "send_followup_dispatch_begin",
            extra={
                "run_id": self.context.run_id,
                "message_length": len(message or ""),
                "artifact_count": len(artifact_ids),
            },
        )
        try:
            await workflow.execute_activity(
                send_followup_to_sandbox,
                SendFollowupToSandboxInput(
                    run_id=self.context.run_id,
                    message=message,
                    posthog_mcp_scopes=self._posthog_mcp_scopes,
                    artifact_ids=artifact_ids,
                    message_id=str(workflow.uuid4()),
                ),
                start_to_close_timeout=timedelta(minutes=35),
                # The activity heartbeats while blocked on the sync delivery
                # call, so a worker restart is detected here instead of at
                # start_to_close. Retries are safe: message_id lets the
                # agent-server drop a redelivery it already accepted, and
                # sentinel-writing failures raise non-retryable.
                heartbeat_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=5),
                    maximum_attempts=SEND_FOLLOWUP_MAX_ATTEMPTS,
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
            # Mark the run as failed so poll_for_turn sees a terminal status
            # immediately instead of waiting for the inactivity timeout.
            self._completion_status = "failed"
            self._completion_error = f"Follow-up delivery failed: {cause_message or e}"
            self._task_completed = True
