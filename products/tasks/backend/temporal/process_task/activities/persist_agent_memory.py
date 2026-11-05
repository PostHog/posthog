import time
from typing import Literal

import structlog
from temporalio import activity

from posthog.dataclasses import frozen
from posthog.temporal.common.utils import asyncify

from products.tasks.backend.exceptions import SandboxNotFoundError, SandboxNotRunningError
from products.tasks.backend.logic.services.agent_memory import (
    MemorySyncCounts,
    persist_sandbox_memory,
    restore_sandbox_memory,
)
from products.tasks.backend.logic.services.sandbox import SandboxBase, get_sandbox_class_for_sandbox_id
from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.metrics import (
    increment_agent_memory_files,
    increment_agent_memory_sync,
    record_agent_memory_sync_latency_ms,
)
from products.tasks.backend.temporal.observability import emit_agent_log

logger = structlog.get_logger(__name__)

# Names the sandbox that last received a complete restore. A persist deletes stored memory files
# only from that sandbox, because any other sandbox may lack files that storage still holds.
AGENT_MEMORY_RESTORED_SANDBOX_STATE_KEY = "agent_memory_restored_sandbox_id"


@frozen
class PersistAgentMemoryInput:
    sandbox_id: str
    run_id: str
    team_id: int
    user_id: int
    reason: str
    # The actor of the most recent follow-up the workflow dispatched; None before any follow-up.
    actor_user_id: int | None = None


@frozen
class PersistAgentMemoryOutput:
    outcome: str = "persisted"
    files_written: int = 0
    files_unchanged: int = 0
    files_deleted: int = 0
    files_skipped: int = 0
    error: str | None = None
    duration_ms: int | None = None


def _record_counts(direction: Literal["persist", "restore"], counts: MemorySyncCounts) -> None:
    increment_agent_memory_files(direction, "written", counts.files_written)
    increment_agent_memory_files(direction, "unchanged", counts.files_unchanged)
    increment_agent_memory_files(direction, "deleted", counts.files_deleted)
    increment_agent_memory_files(direction, "error", counts.errors)
    for reason, count in counts.skipped.items():
        increment_agent_memory_files(direction, f"skipped_{reason}", count)


@frozen
class _RunMemoryState:
    restored_sandbox_id: str | None
    actor_changed: bool


def _run_memory_state(run_id: str, team_id: int, actor_user_id: int | None) -> _RunMemoryState:
    row = TaskRun.objects.filter(id=run_id, team_id=team_id).values_list("state", "task__created_by_id").first()
    state, created_by_id = row if row is not None else (None, None)
    state = state if isinstance(state, dict) else {}
    restored = state.get(AGENT_MEMORY_RESTORED_SANDBOX_STATE_KEY)
    # Once someone other than the creator steers the run, the creator's memory must not be saved
    # from this sandbox. The workflow passes the latest follow-up's actor; run state carries the
    # Slack actor recorded when the run started.
    actor = state.get("slack_actor_user_id")
    actor_changed = (isinstance(actor, int) and not isinstance(actor, bool) and actor != created_by_id) or (
        actor_user_id is not None and actor_user_id != created_by_id
    )
    return _RunMemoryState(
        restored_sandbox_id=restored if isinstance(restored, str) else None, actor_changed=actor_changed
    )


def _finish_persist(
    input: PersistAgentMemoryInput, outcome: str, started_at: float, counts: MemorySyncCounts, error: str | None
) -> PersistAgentMemoryOutput:
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    increment_agent_memory_sync("persist", outcome)
    record_agent_memory_sync_latency_ms("persist", outcome, duration_ms)
    _record_counts("persist", counts)
    log = logger.info if error is None else logger.warning
    log(
        "persist_agent_memory_finished",
        sandbox_id=input.sandbox_id,
        run_id=input.run_id,
        reason=input.reason,
        outcome=outcome,
        files_written=counts.files_written,
        files_unchanged=counts.files_unchanged,
        files_deleted=counts.files_deleted,
        files_skipped=counts.files_skipped,
        duration_ms=duration_ms,
        error=error,
    )
    if error is not None:
        emit_agent_log(input.run_id, "debug", f"Agent memory not saved ({input.reason}): {outcome}")
    elif counts.files_written or counts.files_deleted:
        emit_agent_log(
            input.run_id,
            "debug",
            f"Agent memory saved ({input.reason}): {counts.files_written} written, {counts.files_deleted} removed",
        )
    return PersistAgentMemoryOutput(
        outcome=outcome,
        files_written=counts.files_written,
        files_unchanged=counts.files_unchanged,
        files_deleted=counts.files_deleted,
        files_skipped=counts.files_skipped,
        error=error,
        duration_ms=duration_ms,
    )


@activity.defn
@asyncify
def persist_agent_memory(input: PersistAgentMemoryInput) -> PersistAgentMemoryOutput:
    """Copy the memory the agent changed into object storage.

    Permanent outcomes return a result. Transient failures raise, so Temporal retries the activity
    and the workflow treats an exhausted retry as non-fatal.
    """
    started_at = time.perf_counter()
    counts = MemorySyncCounts()
    try:
        sandbox = get_sandbox_class_for_sandbox_id(input.sandbox_id).get_by_id(input.sandbox_id)
    except SandboxNotFoundError as e:
        return _finish_persist(input, "sandbox_not_found", started_at, counts, f"Sandbox not found: {e}")
    if not sandbox.is_running():
        return _finish_persist(input, "sandbox_not_running", started_at, counts, "Sandbox not running")
    run_state = _run_memory_state(input.run_id, input.team_id, input.actor_user_id)
    if run_state.actor_changed:
        return _finish_persist(input, "actor_changed", started_at, counts, None)
    try:
        counts = persist_sandbox_memory(
            sandbox,
            team_id=input.team_id,
            user_id=input.user_id,
            allow_deletes=run_state.restored_sandbox_id == input.sandbox_id,
        )
    except NotImplementedError:
        # A backend without file listing (hogland) is a supported configuration, not a failure.
        return _finish_persist(input, "unsupported", started_at, counts, None)
    except SandboxNotRunningError:
        return _finish_persist(input, "sandbox_not_running", started_at, counts, "Sandbox not running")
    except Exception:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        increment_agent_memory_sync("persist", "failed")
        record_agent_memory_sync_latency_ms("persist", "failed", duration_ms)
        logger.warning(
            "persist_agent_memory_failed", sandbox_id=input.sandbox_id, run_id=input.run_id, reason=input.reason
        )
        raise
    return _finish_persist(input, "persisted", started_at, counts, None)


def restore_agent_memory_into_sandbox(sandbox: SandboxBase, *, run_id: str, team_id: int, user_id: int) -> None:
    """Write the user's stored memory into a fresh sandbox before agent-server boots. Never raises."""
    started_at = time.perf_counter()
    outcome = "failed"
    counts = MemorySyncCounts()
    error: str | None = None
    try:
        result = restore_sandbox_memory(sandbox, team_id=team_id, user_id=user_id)
        counts = result.counts
        outcome = "restored" if result.complete else "partial"
        if result.complete:
            TaskRun.update_state_atomic(run_id, updates={AGENT_MEMORY_RESTORED_SANDBOX_STATE_KEY: sandbox.id})
    except NotImplementedError:
        outcome = "unsupported"
    except Exception as e:
        error = str(e)
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    increment_agent_memory_sync("restore", outcome)
    record_agent_memory_sync_latency_ms("restore", outcome, duration_ms)
    _record_counts("restore", counts)
    (logger.info if error is None else logger.warning)(
        "restore_agent_memory_finished",
        sandbox_id=sandbox.id,
        run_id=run_id,
        outcome=outcome,
        slugs=counts.slugs,
        files_written=counts.files_written,
        files_deleted=counts.files_deleted,
        files_skipped=counts.files_skipped,
        duration_ms=duration_ms,
        error=error,
    )
    if counts.files_written:
        emit_agent_log(run_id, "debug", f"Agent memory restored: {counts.files_written} files")
