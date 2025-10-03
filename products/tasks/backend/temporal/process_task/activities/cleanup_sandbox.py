import logging
from dataclasses import dataclass

from temporalio import activity

from products.tasks.backend.services.sandbox_environment import NotFoundError, SandboxEnvironment

logger = logging.getLogger(__name__)


@dataclass
class CleanupSandboxInput:
    sandbox_id: str


@activity.defn
async def cleanup_sandbox(input: CleanupSandboxInput) -> None:
    try:
        sandbox = await SandboxEnvironment.get_by_id(input.sandbox_id)
        await sandbox.destroy()
    except NotFoundError:
        pass
    except Exception as e:
        logger.exception(f"Failed to cleanup sandbox {input.sandbox_id}: {e}")
        raise RuntimeError(f"Failed to cleanup sandbox {input.sandbox_id}: {e}")
