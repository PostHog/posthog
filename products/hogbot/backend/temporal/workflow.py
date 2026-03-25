import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import temporalio
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from .activities import (
    CleanupSandboxInput,
    CreateHogbotSandboxInput,
    CreateHogbotSandboxOutput,
    CreateResumeSnapshotInput,
    CreateResumeSnapshotOutput,
    PersistHogbotSnapshotInput,
    ReadSandboxLogsInput,
    StartHogbotServerInput,
    StartHogbotServerOutput,
    WaitForHogbotServerExitInput,
    WaitForHogbotServerExitOutput,
    cleanup_sandbox,
    create_hogbot_sandbox,
    create_resume_snapshot,
    persist_hogbot_snapshot,
    read_sandbox_logs,
    start_hogbot_server,
    wait_for_hogbot_server_exit,
)


@dataclass
class HogbotWorkflowInput:
    team_id: int
    user_id: int | None = None
    server_command: str | None = None
    repository: str | None = None
    github_integration_id: int | None = None
    branch: str | None = None


@dataclass
class HogbotWorkflowOutput:
    success: bool
    status: str
    error: str | None = None
    sandbox_id: str | None = None
    server_url: str | None = None
    connect_token: str | None = None
    snapshot_external_id: str | None = None


@temporalio.workflow.defn(name="hogbot")
class HogbotWorkflow(PostHogWorkflow):
    def __init__(self) -> None:
        self._workflow_id: str | None = None
        self._run_id: str | None = None
        self._phase = "pending"
        self._sandbox_id: str | None = None
        self._server_url: str | None = None
        self._connect_token: str | None = None
        self._ready = False
        self._error: str | None = None

    @staticmethod
    def parse_inputs(inputs: list[str]) -> HogbotWorkflowInput:
        loaded = json.loads(inputs[0])
        return HogbotWorkflowInput(
            team_id=loaded["team_id"],
            user_id=loaded.get("user_id"),
            server_command=loaded.get("server_command"),
            repository=loaded.get("repository"),
            github_integration_id=loaded.get("github_integration_id"),
            branch=loaded.get("branch"),
        )

    @temporalio.workflow.run
    async def run(self, input: HogbotWorkflowInput) -> HogbotWorkflowOutput:
        workflow_info = workflow.info()
        self._workflow_id = workflow_info.workflow_id
        self._run_id = workflow_info.run_id

        sandbox_output: CreateHogbotSandboxOutput | None = None
        server_output: StartHogbotServerOutput | None = None
        wait_output: WaitForHogbotServerExitOutput | None = None
        snapshot_output: CreateResumeSnapshotOutput | None = None

        final_status = "failed"
        final_error: str | None = None

        try:
            self._phase = "starting"

            sandbox_output = await workflow.execute_activity(
                create_hogbot_sandbox,
                CreateHogbotSandboxInput(
                    team_id=input.team_id,
                    user_id=input.user_id,
                    repository=input.repository,
                    github_integration_id=input.github_integration_id,
                    branch=input.branch,
                ),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            self._sandbox_id = sandbox_output.sandbox_id
            self._server_url = sandbox_output.sandbox_url
            self._connect_token = sandbox_output.connect_token

            server_output = await workflow.execute_activity(
                start_hogbot_server,
                StartHogbotServerInput(
                    sandbox_id=sandbox_output.sandbox_id,
                    team_id=input.team_id,
                    sandbox_url=sandbox_output.sandbox_url,
                    connect_token=sandbox_output.connect_token,
                    server_command=input.server_command,
                ),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            self._server_url = server_output.server_url
            self._connect_token = server_output.connect_token
            self._ready = True
            self._phase = "running"

            wait_output = await workflow.execute_activity(
                wait_for_hogbot_server_exit,
                WaitForHogbotServerExitInput(sandbox_id=sandbox_output.sandbox_id),
                start_to_close_timeout=timedelta(days=8),
                heartbeat_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            self._ready = False

            if wait_output.status == "completed":
                self._phase = "snapshotting"
                snapshot_output = await workflow.execute_activity(
                    create_resume_snapshot,
                    CreateResumeSnapshotInput(sandbox_id=sandbox_output.sandbox_id),
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

                if snapshot_output.error:
                    workflow.logger.warning(
                        "hogbot_workflow_snapshot_creation_failed",
                        team_id=input.team_id,
                        sandbox_id=sandbox_output.sandbox_id,
                        error=snapshot_output.error,
                    )
                    final_status = "failed"
                    final_error = snapshot_output.error
                elif snapshot_output.external_id is None:
                    final_status = "failed"
                    final_error = "Snapshot creation completed without returning an external ID"
                else:
                    await workflow.execute_activity(
                        persist_hogbot_snapshot,
                        PersistHogbotSnapshotInput(
                            team_id=input.team_id,
                            snapshot_external_id=snapshot_output.external_id,
                        ),
                        start_to_close_timeout=timedelta(minutes=1),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )
                    final_status = "completed"
                    final_error = None
            else:
                final_status = "failed"
                if wait_output and wait_output.exit_code is not None:
                    final_error = wait_output.error or f"Hogbot server exited with code {wait_output.exit_code}"
                else:
                    final_error = wait_output.error if wait_output else "Hogbot server exited unexpectedly"

            return HogbotWorkflowOutput(
                success=final_status == "completed",
                status=final_status,
                error=final_error,
                sandbox_id=self._sandbox_id,
                server_url=self._server_url,
                connect_token=self._connect_token,
                snapshot_external_id=snapshot_output.external_id if snapshot_output else None,
            )

        except Exception as e:
            final_status = "failed"
            final_error = str(e)
            workflow.logger.exception("hogbot_workflow_failed", team_id=input.team_id, error=final_error)
            return HogbotWorkflowOutput(
                success=False,
                status=final_status,
                error=final_error,
                sandbox_id=self._sandbox_id,
                server_url=self._server_url,
                connect_token=self._connect_token,
                snapshot_external_id=snapshot_output.external_id if snapshot_output else None,
            )

        finally:
            self._ready = False
            self._error = final_error

            if self._sandbox_id:
                self._phase = "cleaning_up"
                try:
                    logs = await workflow.execute_activity(
                        read_sandbox_logs,
                        ReadSandboxLogsInput(sandbox_id=self._sandbox_id),
                        start_to_close_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )
                    if logs:
                        workflow.logger.info("hogbot_workflow_sandbox_logs", sandbox_id=self._sandbox_id, logs=logs)
                except Exception as e:
                    workflow.logger.warning(
                        "hogbot_workflow_log_read_failed",
                        sandbox_id=self._sandbox_id,
                        error=str(e),
                    )

                try:
                    await workflow.execute_activity(
                        cleanup_sandbox,
                        CleanupSandboxInput(sandbox_id=self._sandbox_id),
                        start_to_close_timeout=timedelta(minutes=5),
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )
                except Exception as e:
                    workflow.logger.warning(
                        "hogbot_workflow_cleanup_failed",
                        sandbox_id=self._sandbox_id,
                        error=str(e),
                    )

            self._phase = final_status

    @temporalio.workflow.query
    def get_connection_info(self) -> dict[str, Any]:
        return {
            "workflow_id": self._workflow_id,
            "run_id": self._run_id,
            "phase": self._phase,
            "ready": self._ready,
            "sandbox_id": self._sandbox_id,
            "server_url": self._server_url,
            "connect_token": self._connect_token,
            "error": self._error,
        }

    @temporalio.workflow.query
    def get_status(self) -> dict[str, Any]:
        return {
            "workflow_id": self._workflow_id,
            "run_id": self._run_id,
            "phase": self._phase,
            "ready": self._ready,
            "error": self._error,
            "sandbox_id": self._sandbox_id,
            "server_url": self._server_url,
            "connect_token": self._connect_token,
        }
