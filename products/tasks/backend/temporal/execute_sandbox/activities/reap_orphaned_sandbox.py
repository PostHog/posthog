"""Reap a sandbox left over from a prior execution under the same workflow id.

This activity consolidates what used to be three separate steps in the
workflow — read the persisted sandbox id, destroy the Modal sandbox, clear
the persisted id — into one Temporal activity call. Two reasons:

  * Fewer activity round-trips at startup (the workflow only really cares
    about "did we reap anything" for logging).
  * The read + clear become a single locked pair against `TaskRun.state`
    instead of two independent transactions, so a concurrent state writer
    (slack updates, status transitions) can't interleave between them.

Destroy is best-effort: Modal's per-sandbox TTL is the final backstop, and
a destroy failure does not block the clear — a stale id staying in state
would just be re-reaped (and fail Modal-side again) on the next start.
"""

from dataclasses import dataclass
from typing import Optional

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.logic.services.sandbox import Sandbox
from products.tasks.backend.logic.services.sandbox_usage import close_sandbox_session
from products.tasks.backend.models import SandboxSession, TaskRun
from products.tasks.backend.temporal.execute_sandbox.activities.sandbox_state import SANDBOX_ID_STATE_KEY
from products.tasks.backend.temporal.observability import log_activity_execution


@dataclass
class ReapOrphanedSandboxInput:
    run_id: str


@dataclass
class ReapOrphanedSandboxResult:
    """Outcome of one reap attempt.

    `reaped_sandbox_id` is `None` when there was nothing persisted to reap
    (the typical fresh-start case). When set, `destroy_succeeded` records
    whether the Modal destroy call returned cleanly; either way the state
    key has been cleared by the time this returns.
    """

    reaped_sandbox_id: Optional[str]
    destroy_succeeded: bool


@activity.defn
@asyncify
def reap_orphaned_sandbox(input: ReapOrphanedSandboxInput) -> ReapOrphanedSandboxResult:
    with log_activity_execution("reap_orphaned_sandbox", run_id=input.run_id):
        try:
            task_run = TaskRun.objects.only("state").get(id=input.run_id)
        except TaskRun.DoesNotExist:
            return ReapOrphanedSandboxResult(reaped_sandbox_id=None, destroy_succeeded=True)

        state = task_run.state or {}
        value = state.get(SANDBOX_ID_STATE_KEY)
        sandbox_id = value if isinstance(value, str) and value else None
        if sandbox_id is None:
            return ReapOrphanedSandboxResult(reaped_sandbox_id=None, destroy_succeeded=True)

        destroy_succeeded = True
        try:
            Sandbox.get_by_id(sandbox_id).destroy()
        except Exception:
            # Modal TTL is the backstop; we still clear state below so the
            # next start doesn't re-reap a dead id forever.
            destroy_succeeded = False

        # Best-effort usage-ledger end stamp (swallows its own failures), regardless of
        # destroy outcome — the TTL kills any undead sandbox anyway, and the ledger
        # prefers a slightly early end over an open-ended row.
        close_sandbox_session(sandbox_id, reason=SandboxSession.EndedReason.REAPED)

        TaskRun.update_state_atomic(input.run_id, remove_keys=[SANDBOX_ID_STATE_KEY])
        return ReapOrphanedSandboxResult(reaped_sandbox_id=sandbox_id, destroy_succeeded=destroy_succeeded)
