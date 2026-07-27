"""Activities for persisting / clearing the Modal sandbox id on a TaskRun.

The sandbox id is the only out-of-band record of which Modal sandbox a given
workflow execution owns. We persist it on `TaskRun.state.sandbox_id` so a
follow-up workflow execution (e.g. after a worker crash or a parent restart)
can reap an orphaned sandbox during its startup — see
`reap_orphaned_sandbox.py` for the consolidated read-destroy-clear used at
startup.

State mutations route through `TaskRun.update_state_atomic`, which holds a
row-level lock — concurrent state writers (slack updates, status
transitions, etc.) won't clobber each other.
"""

from dataclasses import dataclass

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
class ClearPersistedSandboxIdInput:
    run_id: str


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

    Called once normal cleanup in the workflow's finally block has succeeded
    so the next workflow start doesn't re-reap an id that's already gone.
    Startup reaping uses `reap_orphaned_sandbox`, which clears state itself.
    """
    with log_activity_execution(
        "clear_persisted_sandbox_id",
        run_id=input.run_id,
    ):
        TaskRun.update_state_atomic(input.run_id, remove_keys=[SANDBOX_ID_STATE_KEY])
