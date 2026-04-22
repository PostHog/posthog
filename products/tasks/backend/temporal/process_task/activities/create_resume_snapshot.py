from dataclasses import dataclass

import structlog
from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import TaskRun
from products.tasks.backend.services.sandbox import get_sandbox_class

logger = structlog.get_logger(__name__)


@dataclass
class CreateResumeSnapshotInput:
    sandbox_id: str
    run_id: str


@dataclass
class CreateResumeSnapshotOutput:
    external_id: str | None
    error: str | None = None


@activity.defn
@asyncify
def create_resume_snapshot(input: CreateResumeSnapshotInput) -> CreateResumeSnapshotOutput:
    """Create a filesystem snapshot of the sandbox for later resume.

    Stores the snapshot external ID on the TaskRun state so the conversation
    API can look it up when resuming.
    """
    SandboxClass = get_sandbox_class()

    try:
        sandbox = SandboxClass.get_by_id(input.sandbox_id)
    except Exception as e:
        logger.warning("create_resume_snapshot_sandbox_not_found", sandbox_id=input.sandbox_id, error=str(e))
        return CreateResumeSnapshotOutput(external_id=None, error=f"Sandbox not found: {e}")

    if not sandbox.is_running():
        return CreateResumeSnapshotOutput(external_id=None, error="Sandbox not running")

    try:
        external_id = sandbox.create_snapshot()
    except Exception as e:
        logger.warning("create_resume_snapshot_snapshot_failed", sandbox_id=input.sandbox_id, error=str(e))
        return CreateResumeSnapshotOutput(external_id=None, error=str(e))

    # Persist snapshot external ID on TaskRun state
    try:
        TaskRun.update_state_atomic(input.run_id, updates={"snapshot_external_id": external_id})
    except Exception as e:
        logger.warning("create_resume_snapshot_persist_failed", run_id=input.run_id, error=str(e))

    activity.logger.info(f"Created resume snapshot {external_id} for sandbox {input.sandbox_id}")
    return CreateResumeSnapshotOutput(external_id=external_id)
