import time
from dataclasses import dataclass

import structlog
from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.constants import (
    DEFAULT_DIRECTORY_RESUME_SNAPSHOT_MOUNT_PATH,
    SNAPSHOT_KIND_DIRECTORY,
    SNAPSHOT_KIND_FILESYSTEM,
    SnapshotKind,
)
from products.tasks.backend.logic.services.sandbox import get_sandbox_class
from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.metrics import increment_snapshot_create, record_snapshot_create_latency_ms

logger = structlog.get_logger(__name__)

PENDING_USER_STATE_KEYS = ["pending_user_message", "pending_user_artifact_ids", "pending_user_message_ts"]


@dataclass
class CreateResumeSnapshotInput:
    sandbox_id: str
    run_id: str
    use_directory_snapshot: bool = False
    snapshot_mount_path: str = DEFAULT_DIRECTORY_RESUME_SNAPSHOT_MOUNT_PATH


@dataclass
class CreateResumeSnapshotOutput:
    external_id: str | None
    snapshot_kind: SnapshotKind | None = None
    snapshot_mount_path: str | None = None
    error: str | None = None


@activity.defn
@asyncify
def create_resume_snapshot(input: CreateResumeSnapshotInput) -> CreateResumeSnapshotOutput:
    """Create a snapshot of the sandbox for later resume.

    Stores the snapshot external ID on the TaskRun state so the conversation
    API can look it up when resuming.
    """
    SandboxClass = get_sandbox_class()
    snapshot_kind: SnapshotKind = SNAPSHOT_KIND_DIRECTORY if input.use_directory_snapshot else SNAPSHOT_KIND_FILESYSTEM
    snapshot_mount_path = input.snapshot_mount_path or DEFAULT_DIRECTORY_RESUME_SNAPSHOT_MOUNT_PATH

    logger.info("create_resume_snapshot_started", sandbox_id=input.sandbox_id, run_id=input.run_id)

    started_at = time.perf_counter()
    try:
        sandbox = SandboxClass.get_by_id(input.sandbox_id)
    except Exception as e:
        logger.warning("create_resume_snapshot_sandbox_not_found", sandbox_id=input.sandbox_id, error=str(e))
        outcome = "sandbox_not_found"
        increment_snapshot_create(snapshot_kind, outcome)
        record_snapshot_create_latency_ms(snapshot_kind, outcome, int((time.perf_counter() - started_at) * 1000))
        return CreateResumeSnapshotOutput(
            external_id=None, snapshot_kind=snapshot_kind, error=f"Sandbox not found: {e}"
        )

    if not sandbox.is_running():
        outcome = "sandbox_not_running"
        increment_snapshot_create(snapshot_kind, outcome)
        record_snapshot_create_latency_ms(snapshot_kind, outcome, int((time.perf_counter() - started_at) * 1000))
        return CreateResumeSnapshotOutput(external_id=None, snapshot_kind=snapshot_kind, error="Sandbox not running")

    outcome = "created"
    try:
        if snapshot_kind == SNAPSHOT_KIND_DIRECTORY:
            external_id = sandbox.create_directory_snapshot(snapshot_mount_path)
        else:
            external_id = sandbox.create_snapshot()
    except Exception as e:
        outcome = "failed"
        logger.warning("create_resume_snapshot_snapshot_failed", sandbox_id=input.sandbox_id, error=str(e))
        increment_snapshot_create(snapshot_kind, outcome)
        record_snapshot_create_latency_ms(snapshot_kind, outcome, int((time.perf_counter() - started_at) * 1000))
        return CreateResumeSnapshotOutput(external_id=None, snapshot_kind=snapshot_kind, error=str(e))
    else:
        increment_snapshot_create(snapshot_kind, outcome)
        record_snapshot_create_latency_ms(snapshot_kind, outcome, int((time.perf_counter() - started_at) * 1000))

    # Persist snapshot external ID on TaskRun state
    try:
        updates = {
            "snapshot_external_id": external_id,
            "snapshot_kind": snapshot_kind,
        }
        remove_keys: list[str] = [*PENDING_USER_STATE_KEYS]
        if snapshot_kind == SNAPSHOT_KIND_DIRECTORY:
            updates["snapshot_mount_path"] = snapshot_mount_path
        else:
            remove_keys.append("snapshot_mount_path")
        TaskRun.update_state_atomic(input.run_id, updates=updates, remove_keys=remove_keys)
    except Exception as e:
        logger.warning("create_resume_snapshot_persist_failed", run_id=input.run_id, error=str(e))

    activity.logger.info(f"Created resume snapshot {external_id} for sandbox {input.sandbox_id}")
    return CreateResumeSnapshotOutput(
        external_id=external_id,
        snapshot_kind=snapshot_kind,
        snapshot_mount_path=snapshot_mount_path if snapshot_kind == SNAPSHOT_KIND_DIRECTORY else None,
    )
