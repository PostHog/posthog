"""Persist the orchestrator's pending-followup queue to `TaskRun.state`.

The orchestrator is long-lived (1:1 with the task run) and may have to
re-queue user-driven follow-ups when a sandbox dies mid-delivery. Keeping
those re-queued payloads only in workflow memory works fine while the
orchestrator's execution is running, but the moment its worker crashes or
the workflow is restarted via Temporal, that in-memory state is gone.

Persisting to `TaskRun.state` solves both visibility (clients can see what's
queued via the same row they already read) and durability (a freshly-started
orchestrator execution reads the queue and seeds its in-memory state).

Activities here are deliberately small: the orchestrator decides *when* to
persist; this module only knows how.
"""

from dataclasses import asdict, dataclass
from typing import Any

from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.observability import log_activity_execution

PENDING_FOLLOWUPS_CHECKPOINT_STATE_KEY = "pending_external_followups_checkpoint"
PENDING_FOLLOWUPS_STATE_KEY = "pending_external_followups"
PENDING_FOLLOWUPS_GENERATION_STATE_KEY = "pending_external_followups_generation"
CI_IDLE_SKIPS_STATE_KEY = "task_management_ci_idle_skips"
CI_WAIT_CHECKS_STATE_KEY = "task_management_ci_wait_checks"
TASK_RUN_NOT_FOUND_ERROR_TYPE = "PendingFollowupsTaskRunNotFound"


@dataclass
class PersistPendingFollowupsInput:
    run_id: str
    # Pre-serialized list of {message, artifact_ids, source, steer, sequence}. The workflow
    # serializes its `PendingExternalFollowup` dataclasses here so the
    # activity doesn't need to import workflow-side types.
    followups: list[dict[str, Any]]


@dataclass(frozen=False)
class PersistPendingFollowupsV2Input:
    run_id: str
    followups: list[dict[str, Any]]
    generation: int
    ci_idle_skips: int | None = None
    ci_wait_checks: int | None = None


@dataclass(frozen=False)
class ReadPendingFollowupsInput:
    run_id: str
    recover_checkpoint: bool = False


@dataclass(frozen=False)
class ReadPendingFollowupsResult:
    """Pending followups read from state. Empty list when nothing is queued."""

    followups: list[dict[str, Any]]
    ci_idle_skips: int = 0
    ci_wait_checks: int = 0


@activity.defn
@asyncify
def persist_pending_followups(input: PersistPendingFollowupsInput) -> None:
    """Write the orchestrator's queued external follow-ups to `TaskRun.state`.

    An empty list is persisted by *removing* the state key entirely — that
    avoids carrying a `[]` value forever and lets `read_pending_followups`
    treat 'no key' and 'empty list' uniformly.
    """
    with log_activity_execution(
        "persist_pending_followups",
        run_id=input.run_id,
        count=len(input.followups),
    ):

        def _persist_if_unversioned(state: dict[str, Any]) -> None:
            if isinstance(state.get(PENDING_FOLLOWUPS_GENERATION_STATE_KEY), int):
                return
            if input.followups:
                state[PENDING_FOLLOWUPS_STATE_KEY] = input.followups
            else:
                state.pop(PENDING_FOLLOWUPS_STATE_KEY, None)

        TaskRun.mutate_state_atomic(input.run_id, _persist_if_unversioned)


def _apply_pending_followups_snapshot(state: dict[str, Any], input: PersistPendingFollowupsV2Input) -> None:
    current_generation = state.get(PENDING_FOLLOWUPS_GENERATION_STATE_KEY)
    if isinstance(current_generation, int) and current_generation >= input.generation:
        return
    state[PENDING_FOLLOWUPS_GENERATION_STATE_KEY] = input.generation
    if input.ci_idle_skips is not None:
        state[CI_IDLE_SKIPS_STATE_KEY] = input.ci_idle_skips
    if input.ci_wait_checks is not None:
        state[CI_WAIT_CHECKS_STATE_KEY] = input.ci_wait_checks
    if input.followups:
        state[PENDING_FOLLOWUPS_STATE_KEY] = input.followups
    else:
        state.pop(PENDING_FOLLOWUPS_STATE_KEY, None)


@activity.defn
@asyncify
def persist_pending_followups_v2(input: PersistPendingFollowupsV2Input) -> None:
    """Persist a queue snapshot unless a newer generation already won."""

    with log_activity_execution(
        "persist_pending_followups_v2",
        run_id=input.run_id,
        count=len(input.followups),
        generation=input.generation,
    ):
        try:
            TaskRun.mutate_state_atomic(input.run_id, lambda state: _apply_pending_followups_snapshot(state, input))
        except TaskRun.DoesNotExist as error:
            raise ApplicationError(
                f"Task run {input.run_id} no longer exists",
                type=TASK_RUN_NOT_FOUND_ERROR_TYPE,
                non_retryable=True,
            ) from error


def _commit_pending_followups_checkpoint(state: dict[str, Any]) -> None:
    checkpoint = state.get(PENDING_FOLLOWUPS_CHECKPOINT_STATE_KEY)
    if checkpoint is None:
        return
    _apply_pending_followups_snapshot(state, PersistPendingFollowupsV2Input(**checkpoint))
    state.pop(PENDING_FOLLOWUPS_CHECKPOINT_STATE_KEY)


@activity.defn
@asyncify
def persist_pending_followups_v3(input: PersistPendingFollowupsV2Input) -> None:
    def stage_checkpoint(state: dict[str, Any]) -> None:
        committed_generation = state.get(PENDING_FOLLOWUPS_GENERATION_STATE_KEY, 0)
        pending_generation = (state.get(PENDING_FOLLOWUPS_CHECKPOINT_STATE_KEY) or {}).get("generation", 0)
        if not isinstance(committed_generation, int):
            committed_generation = 0
        if input.generation <= max(committed_generation, pending_generation):
            return
        state[PENDING_FOLLOWUPS_CHECKPOINT_STATE_KEY] = asdict(input)

    with log_activity_execution(
        "persist_pending_followups_v3", run_id=input.run_id, count=len(input.followups), generation=input.generation
    ):
        try:
            TaskRun.mutate_state_atomic(input.run_id, stage_checkpoint)
            TaskRun.mutate_state_atomic(input.run_id, _commit_pending_followups_checkpoint)
        except TaskRun.DoesNotExist as error:
            raise ApplicationError(
                f"Task run {input.run_id} no longer exists",
                type=TASK_RUN_NOT_FOUND_ERROR_TYPE,
                non_retryable=True,
            ) from error


@activity.defn
@asyncify
def read_pending_followups(input: ReadPendingFollowupsInput) -> ReadPendingFollowupsResult:
    """Read the queued external follow-ups recorded on `TaskRun.state`.

    Safe to call when no record exists or the key holds garbage — returns
    an empty list rather than raising. The orchestrator seeds its in-memory
    queue from this at startup.
    """
    with log_activity_execution(
        "read_pending_followups",
        run_id=input.run_id,
    ):
        try:
            if input.recover_checkpoint:
                TaskRun.mutate_state_atomic(input.run_id, _commit_pending_followups_checkpoint)
            task_run = TaskRun.objects.only("state").get(id=input.run_id)
        except TaskRun.DoesNotExist:
            return ReadPendingFollowupsResult(followups=[])
        state = task_run.state or {}
        ci_idle_skips = state.get(CI_IDLE_SKIPS_STATE_KEY, 0)
        if type(ci_idle_skips) is not int or ci_idle_skips < 0:
            ci_idle_skips = 0
        ci_wait_checks = state.get(CI_WAIT_CHECKS_STATE_KEY, 0)
        if type(ci_wait_checks) is not int or ci_wait_checks < 0:
            ci_wait_checks = 0
        value = state.get(PENDING_FOLLOWUPS_STATE_KEY)
        if not isinstance(value, list):
            return ReadPendingFollowupsResult(followups=[], ci_idle_skips=ci_idle_skips, ci_wait_checks=ci_wait_checks)
        # Drop entries that don't deserialize cleanly — better to lose a
        # malformed item than to crash startup over a stale state shape.
        valid = [item for item in value if isinstance(item, dict)]
        return ReadPendingFollowupsResult(followups=valid, ci_idle_skips=ci_idle_skips, ci_wait_checks=ci_wait_checks)
