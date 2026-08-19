import time
from dataclasses import dataclass

import structlog
from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.constants import (
    DEFAULT_DIRECTORY_RESUME_SNAPSHOT_MOUNT_PATH,
    SNAPSHOT_KIND_DIRECTORY,
    SnapshotKind,
)
from products.tasks.backend.exceptions import (
    SandboxNotRunningError,
    SnapshotFileLimitExceededError,
    SnapshotTimeoutError,
)
from products.tasks.backend.logic.services.sandbox import get_sandbox_class
from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.metrics import increment_snapshot_create, record_snapshot_create_latency_ms
from products.tasks.backend.temporal.observability import emit_agent_log

logger = structlog.get_logger(__name__)

PENDING_USER_STATE_KEYS = [
    "pending_user_message",
    "pending_user_artifact_ids",
    "pending_user_message_id",
    "pending_user_message_ts",
]


@dataclass(frozen=True)
class CreateResumeSnapshotInput:
    sandbox_id: str
    run_id: str
    # Retained for Temporal payload compatibility while existing workflows drain.
    use_directory_snapshot: bool = True
    snapshot_mount_path: str = DEFAULT_DIRECTORY_RESUME_SNAPSHOT_MOUNT_PATH
    reason: str = "teardown"
    allow_pruning: bool = True


@dataclass
class CreateResumeSnapshotOutput:
    external_id: str | None
    snapshot_kind: SnapshotKind | None = None
    snapshot_mount_path: str | None = None
    error: str | None = None
    duration_ms: int | None = None


@activity.defn
@asyncify
def create_resume_snapshot(input: CreateResumeSnapshotInput) -> CreateResumeSnapshotOutput:
    """Create a snapshot of the sandbox for later resume.

    Stores the snapshot external ID on the TaskRun state so the conversation
    API can look it up when resuming.
    """
    SandboxClass = get_sandbox_class()
    snapshot_kind: SnapshotKind = SNAPSHOT_KIND_DIRECTORY
    snapshot_mount_path = input.snapshot_mount_path or DEFAULT_DIRECTORY_RESUME_SNAPSHOT_MOUNT_PATH

    logger.info(
        "create_resume_snapshot_started",
        sandbox_id=input.sandbox_id,
        run_id=input.run_id,
        reason=input.reason,
        snapshot_kind=snapshot_kind,
    )

    started_at = time.perf_counter()
    try:
        sandbox = SandboxClass.get_by_id(input.sandbox_id)
    except Exception as e:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        logger.warning(
            "create_resume_snapshot_sandbox_not_found",
            sandbox_id=input.sandbox_id,
            run_id=input.run_id,
            reason=input.reason,
            snapshot_kind=snapshot_kind,
            duration_ms=duration_ms,
            error=str(e),
        )
        outcome = "sandbox_not_found"
        increment_snapshot_create(snapshot_kind, outcome)
        record_snapshot_create_latency_ms(snapshot_kind, outcome, duration_ms)
        emit_agent_log(input.run_id, "debug", f"Resume snapshot failed ({input.reason}): sandbox not found")
        return CreateResumeSnapshotOutput(
            external_id=None,
            snapshot_kind=snapshot_kind,
            error=f"Sandbox not found: {e}",
            duration_ms=duration_ms,
        )

    if not sandbox.is_running():
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        outcome = "sandbox_not_running"
        logger.warning(
            "create_resume_snapshot_sandbox_not_running",
            sandbox_id=input.sandbox_id,
            run_id=input.run_id,
            reason=input.reason,
            snapshot_kind=snapshot_kind,
            duration_ms=duration_ms,
        )
        increment_snapshot_create(snapshot_kind, outcome)
        record_snapshot_create_latency_ms(snapshot_kind, outcome, duration_ms)
        emit_agent_log(input.run_id, "debug", f"Resume snapshot failed ({input.reason}): sandbox not running")
        return CreateResumeSnapshotOutput(
            external_id=None,
            snapshot_kind=snapshot_kind,
            error="Sandbox not running",
            duration_ms=duration_ms,
        )

    outcome = "created"
    try:
        external_id = sandbox.create_directory_snapshot(snapshot_mount_path)
    except SnapshotFileLimitExceededError as e:
        if not input.allow_pruning:
            outcome = "file_limit_exceeded"
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            logger.warning(
                "create_resume_snapshot_file_limit_exceeded",
                sandbox_id=input.sandbox_id,
                run_id=input.run_id,
                reason=input.reason,
                snapshot_kind=snapshot_kind,
                duration_ms=duration_ms,
                error=str(e),
            )
            increment_snapshot_create(snapshot_kind, outcome)
            record_snapshot_create_latency_ms(snapshot_kind, outcome, duration_ms)
            emit_agent_log(input.run_id, "debug", f"Resume snapshot failed ({input.reason}): file limit exceeded")
            return CreateResumeSnapshotOutput(
                external_id=None,
                snapshot_kind=snapshot_kind,
                error=str(e),
                duration_ms=duration_ms,
            )

        # Prune the reproducible trees (node_modules, virtualenvs, caches) in the live sandbox,
        # then let Temporal retry the whole activity: the next attempt snapshots the now-smaller
        # tree in a fresh 5-minute budget. Doing the prune here and re-raising a transient error —
        # rather than snapshotting again inline — keeps each attempt to a single snapshot, so the
        # activity's timeout can't pre-empt the recovery. If pruning does not bring the tree under
        # the cap, retries exhaust and both callers treat the failed snapshot as non-fatal (the run
        # starts fresh). The resume sandbox reinstalls the pruned trees, so this costs a reinstall.
        outcome = "file_limit_exceeded_pruned"
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        logger.warning(
            "create_resume_snapshot_file_limit_exceeded_pruning",
            sandbox_id=input.sandbox_id,
            run_id=input.run_id,
            reason=input.reason,
            snapshot_kind=snapshot_kind,
            duration_ms=duration_ms,
            error=str(e),
        )
        sandbox.prune_snapshot_heavy_dirs(snapshot_mount_path)
        increment_snapshot_create(snapshot_kind, outcome)
        record_snapshot_create_latency_ms(snapshot_kind, outcome, duration_ms)
        # capture=False: the original SnapshotFileLimitExceededError already carried the signal;
        # this transient wrapper only drives the Temporal retry.
        raise SnapshotTimeoutError(
            f"Pruned workspace over Modal's file-count cap; retrying snapshot: {e}",
            {"sandbox_id": input.sandbox_id, "snapshot_mount_path": snapshot_mount_path},
            cause=e,
            capture=False,
        )
    except SnapshotTimeoutError as e:
        outcome = "transient_error"
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        logger.warning(
            "create_resume_snapshot_transient_error",
            sandbox_id=input.sandbox_id,
            run_id=input.run_id,
            reason=input.reason,
            snapshot_kind=snapshot_kind,
            duration_ms=duration_ms,
            error=str(e),
        )
        increment_snapshot_create(snapshot_kind, outcome)
        record_snapshot_create_latency_ms(snapshot_kind, outcome, duration_ms)
        raise
    except SandboxNotRunningError as e:
        outcome = "sandbox_not_running"
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        logger.warning(
            "create_resume_snapshot_sandbox_not_running",
            sandbox_id=input.sandbox_id,
            run_id=input.run_id,
            reason=input.reason,
            snapshot_kind=snapshot_kind,
            duration_ms=duration_ms,
            error=str(e),
        )
        increment_snapshot_create(snapshot_kind, outcome)
        record_snapshot_create_latency_ms(snapshot_kind, outcome, duration_ms)
        emit_agent_log(input.run_id, "debug", f"Resume snapshot failed ({input.reason}): sandbox not running")
        return CreateResumeSnapshotOutput(
            external_id=None,
            snapshot_kind=snapshot_kind,
            error=str(e),
            duration_ms=duration_ms,
        )
    except Exception as e:
        outcome = "failed"
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        logger.warning(
            "create_resume_snapshot_snapshot_failed",
            sandbox_id=input.sandbox_id,
            run_id=input.run_id,
            reason=input.reason,
            snapshot_kind=snapshot_kind,
            duration_ms=duration_ms,
            error=str(e),
        )
        increment_snapshot_create(snapshot_kind, outcome)
        record_snapshot_create_latency_ms(snapshot_kind, outcome, duration_ms)
        emit_agent_log(input.run_id, "debug", f"Resume snapshot failed ({input.reason}): {e}")
        return CreateResumeSnapshotOutput(
            external_id=None,
            snapshot_kind=snapshot_kind,
            error=str(e),
            duration_ms=duration_ms,
        )
    # Persist snapshot external ID on TaskRun state
    try:
        updates = {
            "snapshot_external_id": external_id,
            "snapshot_kind": snapshot_kind,
            "snapshot_mount_path": snapshot_mount_path,
        }
        TaskRun.update_state_atomic(input.run_id, updates=updates, remove_keys=PENDING_USER_STATE_KEYS)
    except Exception as e:
        outcome = "persist_failed"
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        logger.warning(
            "create_resume_snapshot_persist_failed",
            sandbox_id=input.sandbox_id,
            run_id=input.run_id,
            reason=input.reason,
            snapshot_kind=snapshot_kind,
            snapshot_external_id=external_id,
            duration_ms=duration_ms,
            error=str(e),
        )
        increment_snapshot_create(snapshot_kind, outcome)
        record_snapshot_create_latency_ms(snapshot_kind, outcome, duration_ms)
        emit_agent_log(input.run_id, "debug", f"Resume snapshot failed ({input.reason}): state could not be saved")
        return CreateResumeSnapshotOutput(
            external_id=None,
            snapshot_kind=snapshot_kind,
            error=f"Snapshot state could not be saved: {e}",
            duration_ms=duration_ms,
        )

    duration_ms = int((time.perf_counter() - started_at) * 1000)
    increment_snapshot_create(snapshot_kind, outcome)
    record_snapshot_create_latency_ms(snapshot_kind, outcome, duration_ms)

    logger.info(
        "create_resume_snapshot_created",
        sandbox_id=input.sandbox_id,
        run_id=input.run_id,
        reason=input.reason,
        snapshot_kind=snapshot_kind,
        snapshot_external_id=external_id,
        snapshot_mount_path=snapshot_mount_path,
        duration_ms=duration_ms,
    )
    emit_agent_log(input.run_id, "debug", f"Resume snapshot created ({input.reason}): {external_id}")
    return CreateResumeSnapshotOutput(
        external_id=external_id,
        snapshot_kind=snapshot_kind,
        snapshot_mount_path=snapshot_mount_path,
        duration_ms=duration_ms,
    )
