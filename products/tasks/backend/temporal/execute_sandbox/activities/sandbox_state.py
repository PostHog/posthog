"""Activities for persisting / reading / clearing the Modal sandbox id on a TaskRun.

The sandbox id is the only out-of-band record of which Modal sandbox a given
workflow execution owns. We persist it on `TaskRun.state.sandbox_id` so a
follow-up workflow execution (e.g. after a worker crash or a parent restart)
can reap an orphaned sandbox during its startup — see the reap step in
`ExecuteSandboxWorkflow.run`.

All three activities mutate state through `TaskRun.mutate_state_atomic`, which
holds a row-level lock — concurrent state writers (slack updates, status
transitions, etc.) won't clobber each other.
"""

from dataclasses import dataclass
from typing import Optional

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.observability import log_activity_execution

SANDBOX_ID_STATE_KEY = "sandbox_id"


@dataclass
class PersistSandboxIdInput:
    run_id: str
    sandbox_id: str


@dataclass
class ReadPersistedSandboxIdInput:
    run_id: str


@dataclass
class ClearPersistedSandboxIdInput:
    run_id: str


@dataclass
class SandboxIdResult:
    """Either a sandbox id from prior state, or None when nothing was persisted."""

    sandbox_id: Optional[str]


@activity.defn
@asyncify
def persist_sandbox_id(input: PersistSandboxIdInput) -> None:
    """Record the freshly-created Modal sandbox id on the TaskRun.

    Must run immediately after `create_sandbox_for_repository` succeeds so the
    window in which a sandbox exists with no record is as small as possible.
    Modal's per-sandbox TTL is the last-resort backstop for that window.
    """
    with log_activity_execution(
        "persist_sandbox_id",
        run_id=input.run_id,
        sandbox_id=input.sandbox_id,
    ):
        TaskRun.update_state_atomic(input.run_id, updates={SANDBOX_ID_STATE_KEY: input.sandbox_id})


@activity.defn
@asyncify
def clear_persisted_sandbox_id(input: ClearPersistedSandboxIdInput) -> None:
    """Drop the sandbox id from TaskRun state.

    Called once cleanup has succeeded so the next workflow start doesn't
    re-reap an id that's already gone.
    """
    with log_activity_execution(
        "clear_persisted_sandbox_id",
        run_id=input.run_id,
    ):
        TaskRun.update_state_atomic(input.run_id, remove_keys=[SANDBOX_ID_STATE_KEY])


@activity.defn
@asyncify
def read_persisted_sandbox_id(input: ReadPersistedSandboxIdInput) -> SandboxIdResult:
    """Return any sandbox id recorded on the TaskRun.

    The workflow uses this at startup to decide whether it needs to reap an
    orphaned sandbox left by a prior execution under the same workflow id.
    Safe to call when no record exists — returns `SandboxIdResult(None)`.
    """
    with log_activity_execution(
        "read_persisted_sandbox_id",
        run_id=input.run_id,
    ):
        try:
            task_run = TaskRun.objects.only("state").get(id=input.run_id)
        except TaskRun.DoesNotExist:
            return SandboxIdResult(sandbox_id=None)
        state = task_run.state or {}
        value = state.get(SANDBOX_ID_STATE_KEY)
        return SandboxIdResult(sandbox_id=value if isinstance(value, str) and value else None)
