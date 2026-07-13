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

from dataclasses import dataclass
from typing import Any

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.observability import log_activity_execution

PENDING_FOLLOWUPS_STATE_KEY = "pending_external_followups"


@dataclass
class PersistPendingFollowupsInput:
    run_id: str
    # Pre-serialized list of {message, artifact_ids, source}. The workflow
    # serializes its `PendingExternalFollowup` dataclasses here so the
    # activity doesn't need to import workflow-side types.
    followups: list[dict[str, Any]]


@dataclass
class ReadPendingFollowupsInput:
    run_id: str


@dataclass
class ReadPendingFollowupsResult:
    """Pending followups read from state. Empty list when nothing is queued."""

    followups: list[dict[str, Any]]


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
        if input.followups:
            TaskRun.update_state_atomic(input.run_id, updates={PENDING_FOLLOWUPS_STATE_KEY: input.followups})
        else:
            TaskRun.update_state_atomic(input.run_id, remove_keys=[PENDING_FOLLOWUPS_STATE_KEY])


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
            task_run = TaskRun.objects.only("state").get(id=input.run_id)
        except TaskRun.DoesNotExist:
            return ReadPendingFollowupsResult(followups=[])
        state = task_run.state or {}
        value = state.get(PENDING_FOLLOWUPS_STATE_KEY)
        if not isinstance(value, list):
            return ReadPendingFollowupsResult(followups=[])
        # Drop entries that don't deserialize cleanly — better to lose a
        # malformed item than to crash startup over a stale state shape.
        valid = [item for item in value if isinstance(item, dict)]
        return ReadPendingFollowupsResult(followups=valid)
