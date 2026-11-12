import time
from typing import Any, Literal

import structlog
import posthoganalytics
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


@frozen
class MemoryEventIdentity:
    """Who a memory sync event is captured for: the memory owner and the run's organization and project."""

    distinct_id: str
    organization_id: str
    team_uuid: str


@frozen
class PersistAgentMemoryInput:
    sandbox_id: str
    run_id: str
    team_id: int
    user_id: int
    reason: str
    # The actor of the most recent follow-up the workflow dispatched; None before any follow-up.
    actor_user_id: int | None = None
    identity: MemoryEventIdentity | None = None


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


def _capture_memory_event(
    event: str,
    identity: MemoryEventIdentity | None,
    *,
    run_id: str,
    outcome: str,
    counts: MemorySyncCounts,
    duration_ms: int,
    error: str | None,
    **extra: Any,
) -> None:
    """Capture the sync as a product event so memory usage and cap hits are visible per user. Never raises."""
    if identity is None:
        return
    properties: dict[str, Any] = {
        "run_id": run_id,
        "outcome": outcome,
        "slugs": counts.slugs,
        "files_written": counts.files_written,
        "files_unchanged": counts.files_unchanged,
        "files_deleted": counts.files_deleted,
        "files_skipped": counts.files_skipped,
        "files_errored": counts.errors,
        "duration_ms": duration_ms,
        "error": error,
        **extra,
    }
    for reason, count in counts.skipped.items():
        properties[f"skipped_{reason}"] = count
    try:
        posthoganalytics.capture(
            distinct_id=identity.distinct_id,
            event=event,
            properties=properties,
            groups={"organization": identity.organization_id, "project": identity.team_uuid},
        )
    except Exception:
        logger.warning("agent_memory_event_capture_failed", event=event, run_id=run_id, exc_info=True)


def _driven_by_another_member(run_id: str, team_id: int, actor_user_id: int | None) -> bool:
    row = TaskRun.objects.filter(id=run_id, team_id=team_id).values_list("state", "task__created_by_id").first()
    state, created_by_id = row if row is not None else (None, None)
    state = state if isinstance(state, dict) else {}
    # Once someone other than the creator steers the run, the creator's memory must not be saved
    # from this sandbox. The workflow passes the latest follow-up's actor; run state carries the
    # Slack actor recorded when the run started and the lock stamped by any earlier such follow-up.
    if state.get("agent_memory_locked") is True:
        return True
    actor = state.get("slack_actor_user_id")
    return (isinstance(actor, int) and not isinstance(actor, bool) and actor != created_by_id) or (
        actor_user_id is not None and actor_user_id != created_by_id
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
    _capture_memory_event(
        "agent_memory_persisted",
        input.identity,
        run_id=input.run_id,
        outcome=outcome,
        counts=counts,
        duration_ms=duration_ms,
        error=error,
        reason=input.reason,
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
    if _driven_by_another_member(input.run_id, input.team_id, input.actor_user_id):
        return _finish_persist(input, "actor_changed", started_at, counts, None)
    try:
        counts = persist_sandbox_memory(sandbox, team_id=input.team_id, user_id=input.user_id)
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


def restore_agent_memory_into_sandbox(
    sandbox: SandboxBase, *, run_id: str, team_id: int, user_id: int, identity: MemoryEventIdentity | None = None
) -> None:
    """Write the user's stored memory into a fresh sandbox before agent-server boots. Never raises."""
    started_at = time.perf_counter()
    outcome = "failed"
    counts = MemorySyncCounts()
    error: str | None = None
    try:
        result = restore_sandbox_memory(sandbox, team_id=team_id, user_id=user_id)
        counts = result.counts
        if result.snapshot_baseline_kept:
            outcome = "snapshot_baseline_kept"
        else:
            outcome = "restored" if result.complete else "partial"
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
    _capture_memory_event(
        "agent_memory_restored",
        identity,
        run_id=run_id,
        outcome=outcome,
        counts=counts,
        duration_ms=duration_ms,
        error=error,
    )
    if counts.files_written:
        emit_agent_log(run_id, "debug", f"Agent memory restored: {counts.files_written} files")
