import logging
from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.services.sandbox import Sandbox
from products.tasks.backend.temporal.observability import log_activity_execution

logger = logging.getLogger(__name__)

MAX_LOG_SIZE = 50_000


@dataclass
class ReadSandboxLogsInput:
    sandbox_id: str


@activity.defn
@asyncify
def read_sandbox_logs(input: ReadSandboxLogsInput) -> str:
    """Read agent-server logs from the sandbox before it's destroyed."""
    with log_activity_execution(
        "read_sandbox_logs",
        sandbox_id=input.sandbox_id,
    ):
        try:
            sandbox = Sandbox.get_by_id(input.sandbox_id)
            result = sandbox.execute(
                f"tail -c {MAX_LOG_SIZE} /tmp/agent-server.log 2>/dev/null || echo 'No log file found'",
                timeout_seconds=10,
            )
            logs = result.stdout.strip()
            if logs:
                logger.info(f"Sandbox {input.sandbox_id} agent-server logs:\n{logs}")
            return logs
        except Exception as e:
            logger.warning(f"Failed to read sandbox logs: {e}")
            return f"Failed to read logs: {e}"
