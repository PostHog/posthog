import base64
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from temporalio import activity

from products.tasks.backend.services.sandbox import Sandbox
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext

logger = logging.getLogger(__name__)


@dataclass
class StartAgentServerInput:
    context: TaskProcessingContext
    sandbox_id: str
    initial_prompt: Optional[str] = None


@dataclass
class StartAgentServerOutput:
    success: bool
    error: Optional[str] = None


@activity.defn
async def start_agent_server(input: StartAgentServerInput) -> StartAgentServerOutput:
    """
    Start the agent server in the sandbox for cloud execution.
    The server connects back to the PostHog API via SSE for bidirectional communication.
    """
    ctx = input.context
    sandbox_id = input.sandbox_id
    logger.info(f"Starting agent server in sandbox {sandbox_id} for run {ctx.run_id}")

    try:
        sandbox = Sandbox.get_by_id(sandbox_id)

        org, repo = ctx.repository.lower().split("/")
        repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        command_parts = [
            "node",
            "/scripts/node_modules/@posthog/agent-server/dist/index.js",
            f"--taskId {ctx.task_id}",
            f"--runId {ctx.run_id}",
            f"--repositoryPath {repo_path}",
        ]

        if input.initial_prompt:
            encoded = base64.b64encode(input.initial_prompt.encode()).decode()
            command_parts.append(f"--initialPrompt {encoded}")

        command = " ".join(command_parts)

        sandbox.execute_background(command)
        logger.info(f"Agent server started in background in sandbox {sandbox_id}")

        await asyncio.sleep(2)

        check_result = sandbox.execute("pgrep -f agent-server", timeout_seconds=5)
        if check_result.exit_code != 0:
            log_result = sandbox.execute(
                "cat /tmp/agent-server.log 2>/dev/null || echo 'No log file'",
                timeout_seconds=5,
            )
            return StartAgentServerOutput(
                success=False,
                error=f"Agent server process not found after startup. Log: {log_result.stdout}",
            )

        logger.info(f"Agent server verified running (PID: {check_result.stdout.strip()})")
        return StartAgentServerOutput(success=True)

    except Exception as e:
        logger.exception(f"Failed to start agent server: {e}")
        return StartAgentServerOutput(success=False, error=str(e))
