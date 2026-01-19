"""
Cloud Session Workflow

Manages the lifecycle of a cloud agent session:
1. Provisions sandbox
2. Starts agent server (which connects back via SSE)
3. Keeps sandbox alive until close signal or timeout
4. Cleans up sandbox
"""

import json
import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

import temporalio
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from products.tasks.backend.temporal.process_task.activities.cleanup_sandbox import CleanupSandboxInput, cleanup_sandbox
from products.tasks.backend.temporal.process_task.activities.update_task_run_status import (
    UpdateTaskRunStatusInput,
    update_task_run_status,
)

from .activities.provision_sandbox import ProvisionSandboxInput, ProvisionSandboxOutput, provision_sandbox
from .activities.start_agent_server import StartAgentServerInput, StartAgentServerOutput, start_agent_server

logger = logging.getLogger(__name__)

INACTIVITY_TIMEOUT_MINUTES = 15


@dataclass
class CloudSessionInput:
    run_id: str
    task_id: str
    repository: str
    team_id: int
    github_integration_id: Optional[int] = None
    snapshot_id: Optional[str] = None


@dataclass
class CloudSessionOutput:
    success: bool
    sandbox_id: Optional[str] = None
    error: Optional[str] = None


@temporalio.workflow.defn(name="cloud-session")
class CloudSessionWorkflow(PostHogWorkflow):
    def __init__(self) -> None:
        self._should_close = False
        self._last_activity_time = workflow.now()
        self._sandbox_id: Optional[str] = None

    @staticmethod
    def parse_inputs(inputs: list[str]) -> CloudSessionInput:
        loaded = json.loads(inputs[0])
        return CloudSessionInput(
            run_id=loaded["run_id"],
            task_id=loaded["task_id"],
            repository=loaded["repository"],
            team_id=loaded["team_id"],
            github_integration_id=loaded.get("github_integration_id"),
            snapshot_id=loaded.get("snapshot_id"),
        )

    @temporalio.workflow.signal
    def close(self) -> None:
        """Signal to close the session and clean up."""
        self._should_close = True

    @temporalio.workflow.signal
    def heartbeat(self) -> None:
        """Signal to keep the session alive."""
        self._last_activity_time = workflow.now()

    @temporalio.workflow.run
    async def run(self, input: CloudSessionInput) -> CloudSessionOutput:
        try:
            await self._update_task_run_status(input.run_id, "in_progress")

            sandbox_output = await self._provision_sandbox(input)
            self._sandbox_id = sandbox_output.sandbox_id

            agent_result = await self._start_agent_server(
                sandbox_id=self._sandbox_id,
                run_id=input.run_id,
                task_id=input.task_id,
                repository=input.repository,
            )

            if not agent_result.success:
                await self._update_task_run_status(input.run_id, "failed", agent_result.error)
                return CloudSessionOutput(
                    success=False,
                    sandbox_id=self._sandbox_id,
                    error=agent_result.error,
                )

            self._last_activity_time = workflow.now()
            await self._wait_for_close_or_timeout()

            await self._update_task_run_status(input.run_id, "completed")
            return CloudSessionOutput(success=True, sandbox_id=self._sandbox_id)

        except asyncio.CancelledError:
            await self._update_task_run_status(input.run_id, "cancelled")
            raise

        except Exception as e:
            error_message = str(e)[:500]
            await self._update_task_run_status(input.run_id, "failed", error_message)
            return CloudSessionOutput(success=False, sandbox_id=self._sandbox_id, error=str(e))

        finally:
            if self._sandbox_id:
                await self._cleanup_sandbox(self._sandbox_id)

    async def _wait_for_close_or_timeout(self) -> None:
        """Wait until close signal or inactivity timeout."""
        timeout = timedelta(minutes=INACTIVITY_TIMEOUT_MINUTES)

        while not self._should_close:
            now = workflow.now()
            time_since_activity = now - self._last_activity_time
            remaining = timeout - time_since_activity

            if remaining <= timedelta(0):
                workflow.logger.info("Session timed out due to inactivity")
                break

            try:
                await workflow.wait_condition(
                    lambda: self._should_close,
                    timeout=remaining,
                )
            except TimeoutError:
                pass

    async def _provision_sandbox(self, input: CloudSessionInput) -> ProvisionSandboxOutput:
        return await workflow.execute_activity(
            provision_sandbox,
            ProvisionSandboxInput(
                run_id=input.run_id,
                task_id=input.task_id,
                repository=input.repository,
                github_integration_id=input.github_integration_id,
                snapshot_id=input.snapshot_id,
            ),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _start_agent_server(
        self,
        sandbox_id: str,
        run_id: str,
        task_id: str,
        repository: str,
    ) -> StartAgentServerOutput:
        return await workflow.execute_activity(
            start_agent_server,
            StartAgentServerInput(
                sandbox_id=sandbox_id,
                run_id=run_id,
                task_id=task_id,
                repository=repository,
            ),
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

    async def _cleanup_sandbox(self, sandbox_id: str) -> None:
        await workflow.execute_activity(
            cleanup_sandbox,
            CleanupSandboxInput(sandbox_id=sandbox_id),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _update_task_run_status(self, run_id: str, status: str, error_message: Optional[str] = None) -> None:
        await workflow.execute_activity(
            update_task_run_status,
            UpdateTaskRunStatusInput(
                run_id=run_id,
                status=status,
                error_message=error_message,
            ),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
