import logging
from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.services.sandbox import Sandbox
from products.tasks.backend.temporal.exceptions import SandboxNotFoundError
from products.tasks.backend.temporal.observability import log_activity_execution

logger = logging.getLogger(__name__)


@dataclass
class CleanupSandboxInput:
    sandbox_id: str


@activity.defn
@asyncify
def cleanup_sandbox(input: CleanupSandboxInput) -> None:
    with log_activity_execution(
        "cleanup_sandbox",
        sandbox_id=input.sandbox_id,
    ):
        try:
            sandbox = Sandbox.get_by_id(input.sandbox_id)
            sandbox.destroy()
        except SandboxNotFoundError:
            pass
