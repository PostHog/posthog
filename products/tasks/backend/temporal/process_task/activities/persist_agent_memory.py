import time
from typing import Literal

import structlog
from temporalio import activity

from posthog.dataclasses import frozen
from posthog.temporal.common.utils import asyncify

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


@frozen
class PersistAgentMemoryOutput:
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


def _restored_into(run_id: str, team_id: int, sandbox_id: str) -> bool:
    state = TaskRun.objects.filter(id=run_id, team_id=team_id).values_list("state", flat=True).first()
    return isinstance(state, dict) and state.get(AGENT_MEMORY_RESTORED_SANDBOX_STATE_KEY) == sandbox_id


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
    """Copy the sandbox's Claude Code auto memory into object storage. Never fails the run."""
    started_at = time.perf_counter()
    counts = MemorySyncCounts()
    try:
        sandbox = get_sandbox_class_for_sandbox_id(input.sandbox_id).get_by_id(input.sandbox_id)
    except Exception as e:
        return _finish_persist(input, "sandbox_not_found", started_at, counts, f"Sandbox not found: {e}")
    if not sandbox.is_running():
        return _finish_persist(input, "sandbox_not_running", started_at, counts, "Sandbox not running")
    try:
        allow_deletes = _restored_into(input.run_id, input.team_id, input.sandbox_id)
        counts = persist_sandbox_memory(sandbox, user_id=input.user_id, allow_deletes=allow_deletes)
    except NotImplementedError:
        # A backend without file listing (hogland) is a supported configuration, not a failure.
        return _finish_persist(input, "unsupported", started_at, counts, None)
    except Exception as e:
        return _finish_persist(input, "failed", started_at, counts, str(e))
    outcome = "partial" if counts.errors else "persisted"
    return _finish_persist(input, outcome, started_at, counts, None)


def restore_agent_memory_into_sandbox(sandbox: SandboxBase, *, run_id: str, user_id: int) -> None:
    """Write the user's stored memory into a fresh sandbox before agent-server boots. Never raises."""
    started_at = time.perf_counter()
    outcome = "failed"
    counts = MemorySyncCounts()
    error: str | None = None
    try:
        result = restore_sandbox_memory(sandbox, user_id=user_id)
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
