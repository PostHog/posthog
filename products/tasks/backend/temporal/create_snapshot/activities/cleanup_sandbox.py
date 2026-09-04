import logging
from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.logic.services.sandbox import get_sandbox_class_for_sandbox_id
from products.tasks.backend.temporal.observability import log_activity_execution

logger = logging.getLogger(__name__)


@dataclass
class CleanupSandboxInput:
    sandbox_id: str


@activity.defn(name="snapshot_cleanup_sandbox")
@asyncify
def cleanup_sandbox(input: CleanupSandboxInput) -> None:
    with log_activity_execution(
        "cleanup_sandbox",
        sandbox_id=input.sandbox_id,
    ):
        try:
            sandbox = get_sandbox_class_for_sandbox_id(input.sandbox_id).get_by_id(input.sandbox_id)
            sandbox.destroy()
        except Exception:
            # The sandbox has a timeout, and it will eventually terminate if we failed to cleanup
            pass
