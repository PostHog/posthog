"""Activities for stack runs. The run's inputs and results stay in Postgres, so only ids cross Temporal."""

from uuid import UUID

from temporalio import activity

from posthog.temporal.common.heartbeat_sync import send_heartbeat
from posthog.temporal.common.utils import asyncify

from products.stacks.backend.logic import cleanup, runs
from products.stacks.backend.temporal.types import StackCleanupInput, StackRunInput


def _beat() -> None:
    # The push body runs on a worker thread, and an async activity accepts heartbeats only on its event loop.
    send_heartbeat()
    if activity.is_cancelled():
        raise runs.RunCancelled


@activity.defn(name="stacks-compute-diff")
@asyncify
def compute_stack_diff(input: StackRunInput) -> None:
    runs.compute_diff(input.team_id, UUID(input.diff_id))


@activity.defn(name="stacks-push-diff")
@asyncify
def push_stack_diff(input: StackRunInput) -> None:
    if input.attempt_id is None:
        return
    runs.run_push(input.team_id, UUID(input.diff_id), UUID(input.attempt_id), beat=_beat)


@activity.defn(name="stacks-cleanup")
@asyncify
def clean_up_stacks(input: StackCleanupInput) -> None:
    cleanup.sweep()
