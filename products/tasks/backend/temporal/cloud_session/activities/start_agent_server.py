import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from temporalio import activity

from products.tasks.backend.services.sandbox import Sandbox

logger = logging.getLogger(__name__)


@dataclass
class StartAgentServerInput:
    sandbox_id: str
    run_id: str
    task_id: str
    repository: str


@dataclass
class StartAgentServerOutput:
    success: bool
    error: Optional[str] = None


@activity.defn
async def start_agent_server(input: StartAgentServerInput) -> StartAgentServerOutput:
    logger.info(f"Starting agent server in sandbox {input.sandbox_id}")

    try:
        sandbox = Sandbox.get_by_id(input.sandbox_id)

        org, repo = input.repository.lower().split("/")
        repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        command = (
            f"node /scripts/runAgentServer.mjs "
            f"--taskId {input.task_id} "
            f"--runId {input.run_id} "
            f"--repositoryPath {repo_path}"
        )

        sandbox.execute_background(command)
        logger.info(f"Agent server started in background in sandbox {input.sandbox_id}")

        await asyncio.sleep(2)

        check_result = sandbox.execute("pgrep -f runAgentServer", timeout_seconds=5)
        if check_result.exit_code != 0:
            log_result = sandbox.execute("cat /tmp/agent-server.log 2>/dev/null || echo 'No log file'", timeout_seconds=5)
            return StartAgentServerOutput(
                success=False,
                error=f"Agent server process not found after startup. Log: {log_result.stdout}",
            )

        logger.info(f"Agent server verified running (PID: {check_result.stdout.strip()})")
        return StartAgentServerOutput(success=True)

    except Exception as e:
        logger.exception(f"Failed to start agent server: {e}")
        return StartAgentServerOutput(success=False, error=str(e))
