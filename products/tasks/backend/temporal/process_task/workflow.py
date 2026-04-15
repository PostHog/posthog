import json
import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional

from django.conf import settings

import temporalio
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.workflow import ParentClosePolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.oauth import PosthogMcpScopes

from products.tasks.backend.services.sandbox import is_public_sandbox_repo
from products.tasks.backend.temporal.create_snapshot.workflow import CreateSnapshotForRepositoryInput

from .activities.cleanup_sandbox import CleanupSandboxInput, cleanup_sandbox
from .activities.create_resume_snapshot import CreateResumeSnapshotInput, create_resume_snapshot
from .activities.execute_task_in_sandbox import ExecuteTaskOutput
from .activities.forward_pending_message import forward_pending_user_message
from .activities.get_sandbox_for_repository import GetSandboxForRepositoryOutput
from .activities.get_task_processing_context import (
    GetTaskProcessingContextInput,
    TaskProcessingContext,
    get_task_processing_context,
)
from .activities.post_slack_update import PostSlackUpdateInput, post_slack_update
from .activities.provision_sandbox import (
    CheckoutBranchInSandboxInput,
    CloneRepositoryInSandboxInput,
    CreateSandboxForRepositoryInput,
    PrepareSandboxForRepositoryInput,
    checkout_branch_in_sandbox,
    clone_repository_in_sandbox,
    create_sandbox_for_repository,
    prepare_sandbox_for_repository,
)
from .activities.read_sandbox_logs import ReadSandboxLogsInput, read_sandbox_logs
from .activities.relay_sandbox_events import RelaySandboxEventsInput, relay_sandbox_events
from .activities.send_followup_to_sandbox import SendFollowupToSandboxInput, send_followup_to_sandbox
from .activities.start_agent_server import StartAgentServerInput, StartAgentServerOutput, start_agent_server
from .activities.track_workflow_event import TrackWorkflowEventInput, track_workflow_event
from .activities.update_task_run_status import UpdateTaskRunStatusInput, update_task_run_status


@dataclass
class ProcessTaskInput:
    run_id: str
    create_pr: bool = True
    slack_thread_context: Optional[dict[str, Any]] = None
    posthog_mcp_scopes: PosthogMcpScopes = "read_only"


@dataclass
class ProcessTaskOutput:
    success: bool
    task_result: Optional[ExecuteTaskOutput] = None
    error: Optional[str] = None
    sandbox_id: Optional[str] = None


INACTIVITY_TIMEOUT_MINUTES = 30
PENDING_MESSAGE_FORWARD_TIMEOUT_SECONDS = 180


@temporalio.workflow.defn(name="process-task")
class ProcessTaskWorkflow(PostHogWorkflow):
    def __init__(self) -> None:
        self._context: Optional[TaskProcessingContext] = None
        self._slack_thread_context: Optional[dict[str, Any]] = None
        self._posthog_mcp_scopes: PosthogMcpScopes = "read_only"
        self._sandbox_id_for_cleanup: Optional[str] = None
        self._task_completed: bool = False
        self._completion_status: str = "completed"
        self._completion_error: Optional[str] = None
        self._heartbeat_received: bool = False
        self._pending_followup: Optional[str] = None

    @property
    def context(self) -> TaskProcessingContext:
        if self._context is None:
            raise RuntimeError("context accessed before being set")
        return self._context

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ProcessTaskInput:
        loaded = json.loads(inputs[0])
        return ProcessTaskInput(
            run_id=loaded["run_id"],
            create_pr=loaded.get("create_pr", True),
            slack_thread_context=loaded.get("slack_thread_context"),
            posthog_mcp_scopes=loaded.get("posthog_mcp_scopes", "read_only"),
        )

    @temporalio.workflow.run
    async def run(self, input: ProcessTaskInput) -> ProcessTaskOutput:
        sandbox_id = None
        sandbox_cleaned = False
        timed_out = False
        run_id = input.run_id
        self._sandbox_id_for_cleanup = None
        self._slack_thread_context = input.slack_thread_context

        try:
            self._context = await self._get_task_processing_context(input)
            self._posthog_mcp_scopes = input.posthog_mcp_scopes
            await self._update_task_run_status("in_progress")

            await self._track_workflow_event(
                "task_run_started",
                {
                    "run_id": run_id,
                    "task_id": self.context.task_id,
                    "repository": self.context.repository,
                    "team_id": self.context.team_id,
                },
            )

            await self._post_slack_update()

            sandbox_output = await self._get_sandbox_for_repository()
            sandbox_id = sandbox_output.sandbox_id

            # TODO(tasks): Re-enable snapshot creation
            # if sandbox_output.should_create_snapshot and self.context.repository and self.context.github_integration_id:
            #     await self._trigger_snapshot_workflow()

            await self._post_slack_update()

            # Start agent-server for direct connection from PostHog Code
            agent_server_output = await self._start_agent_server(sandbox_output)

            await self._track_workflow_event(
                "sandbox_started",
                {
                    "run_id": run_id,
                    "task_id": self.context.task_id,
                    "sandbox_id": sandbox_id,
                    "sandbox_url": agent_server_output.sandbox_url,
                    "used_snapshot": sandbox_output.used_snapshot,
                    "repository": self.context.repository,
                },
            )

            relay_task = asyncio.ensure_future(self._relay_sandbox_events(agent_server_output, sandbox_id=sandbox_id))

            if self._should_forward_pending_user_message():
                try:
                    await self._forward_pending_user_message()
                except Exception as e:
                    workflow.logger.warning(
                        "forward_pending_user_message_failed_non_fatal",
                        run_id=self.context.run_id,
                        error=str(e),
                    )

            # Wait for completion signal or inactivity timeout.
            # Heartbeat signals reset the inactivity timer, keeping the workflow alive
            # as long as the agent is actively producing logs.
            while not self._task_completed:
                try:
                    await workflow.wait_condition(
                        lambda: self._task_completed or self._heartbeat_received or self._pending_followup is not None,
                        timeout=timedelta(minutes=INACTIVITY_TIMEOUT_MINUTES),
                    )
                except TimeoutError:
                    timed_out = True
                    break

                if self._pending_followup is not None:
                    message = self._pending_followup
                    self._pending_followup = None
                    await self._send_followup_to_sandbox(message)
                    continue

                if self._heartbeat_received and not self._task_completed:
                    self._heartbeat_received = False
                    continue

            # Stop the relay now that the main loop is done
            await self._cancel_relay(relay_task)

            if self._task_completed:
                await self._update_task_run_status(self._completion_status, error_message=self._completion_error)
            elif timed_out:
                await self._update_task_run_status("completed", error_message="Run timed out due to inactivity")

            await self._post_slack_update()

            return ProcessTaskOutput(
                success=True,
                task_result=None,
                error=None,
                sandbox_id=sandbox_id,
            )

        except asyncio.CancelledError:
            current_sandbox_id = sandbox_id or self._sandbox_id_for_cleanup
            if self._context:
                await self._track_workflow_event(
                    "task_run_cancelled",
                    {
                        "run_id": run_id,
                        "task_id": self.context.task_id,
                        "repository": self.context.repository,
                        "team_id": self.context.team_id,
                    },
                )
            await self._update_task_run_status("cancelled")
            if current_sandbox_id:
                await self._cleanup_sandbox(current_sandbox_id)
                sandbox_id = None
                self._sandbox_id_for_cleanup = None
            raise

        except Exception as e:
            current_sandbox_id = sandbox_id or self._sandbox_id_for_cleanup
            error_message = str(e)[:500]
            if self._context:
                await self._track_workflow_event(
                    "task_run_failed",
                    {
                        "run_id": run_id,
                        "task_id": self.context.task_id,
                        "error_type": type(e).__name__,
                        "error_message": error_message,
                        "sandbox_id": current_sandbox_id,
                    },
                )
                await self._update_task_run_status("failed", error_message=error_message)
                await self._post_slack_update()

            return ProcessTaskOutput(
                success=False,
                task_result=None,
                error=str(e),
                sandbox_id=current_sandbox_id,
            )

        finally:
            cleanup_sandbox_id = sandbox_id or self._sandbox_id_for_cleanup
            if cleanup_sandbox_id:
                # Create a resume snapshot for interactive sandboxes before cleanup
                if self._context and self._context.mode == "interactive":
                    await self._create_resume_snapshot(cleanup_sandbox_id)

                await self._read_sandbox_logs(cleanup_sandbox_id)
                await self._cleanup_sandbox(cleanup_sandbox_id)
                sandbox_cleaned = True
                self._sandbox_id_for_cleanup = None

            if sandbox_cleaned and self._slack_thread_context and self._context:
                await self._post_slack_update(sandbox_cleaned=True)

    async def _get_task_processing_context(self, input: ProcessTaskInput) -> TaskProcessingContext:
        return await workflow.execute_activity(
            get_task_processing_context,
            GetTaskProcessingContextInput(run_id=input.run_id, create_pr=input.create_pr),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _get_sandbox_for_repository(self) -> GetSandboxForRepositoryOutput:
        prepared = await workflow.execute_activity(
            prepare_sandbox_for_repository,
            PrepareSandboxForRepositoryInput(context=self.context),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        created = await workflow.execute_activity(
            create_sandbox_for_repository,
            CreateSandboxForRepositoryInput(context=self.context, prepared=prepared),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        self._sandbox_id_for_cleanup = created.sandbox_id

        can_clone_without_integration = is_public_sandbox_repo(prepared.repository)
        has_clone_credentials = self.context.github_integration_id is not None or can_clone_without_integration

        if prepared.repository and not prepared.used_snapshot and has_clone_credentials:
            await workflow.execute_activity(
                clone_repository_in_sandbox,
                CloneRepositoryInSandboxInput(
                    context=self.context,
                    sandbox_id=created.sandbox_id,
                    repository=prepared.repository,
                    github_token=prepared.github_token,
                    shallow_clone=prepared.shallow_clone,
                ),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

        if prepared.repository and prepared.branch and has_clone_credentials:
            await workflow.execute_activity(
                checkout_branch_in_sandbox,
                CheckoutBranchInSandboxInput(
                    context=self.context,
                    sandbox_id=created.sandbox_id,
                    repository=prepared.repository,
                    branch=prepared.branch,
                    github_token=prepared.github_token,
                    shallow_clone=prepared.shallow_clone,
                    used_snapshot=prepared.used_snapshot,
                ),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

        return GetSandboxForRepositoryOutput(
            sandbox_id=created.sandbox_id,
            sandbox_url=created.sandbox_url,
            connect_token=created.connect_token,
            used_snapshot=prepared.used_snapshot,
            should_create_snapshot=prepared.should_create_snapshot,
        )

    async def _cleanup_sandbox(self, sandbox_id: str) -> None:
        cleanup_input = CleanupSandboxInput(sandbox_id=sandbox_id)
        await workflow.execute_activity(
            cleanup_sandbox,
            cleanup_input,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _read_sandbox_logs(self, sandbox_id: str) -> None:
        try:
            logs = await workflow.execute_activity(
                read_sandbox_logs,
                ReadSandboxLogsInput(sandbox_id=sandbox_id, run_id=self.context.run_id),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            if logs:
                workflow.logger.info(f"Agent-server logs from sandbox {sandbox_id}:\n{logs}")
        except Exception as e:
            workflow.logger.warning(f"Failed to read sandbox logs: {e}")

    async def _start_agent_server(self, sandbox_output: GetSandboxForRepositoryOutput) -> StartAgentServerOutput:
        return await workflow.execute_activity(
            start_agent_server,
            StartAgentServerInput(
                context=self.context,
                sandbox_id=sandbox_output.sandbox_id,
                sandbox_url=sandbox_output.sandbox_url,
                sandbox_connect_token=sandbox_output.connect_token,
                posthog_mcp_scopes=self._posthog_mcp_scopes,
            ),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _forward_pending_user_message(self) -> None:
        await workflow.execute_activity(
            forward_pending_user_message,
            self.context.run_id,
            start_to_close_timeout=timedelta(seconds=PENDING_MESSAGE_FORWARD_TIMEOUT_SECONDS),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

    def _should_forward_pending_user_message(self) -> bool:
        if not self._context:
            return False

        is_resume = bool((self.context.state or {}).get("resume_from_run_id"))
        return self.context.mode != "interactive" and not is_resume

    async def _track_workflow_event(self, event_name: str, properties: dict) -> None:
        track_input = TrackWorkflowEventInput(
            event_name=event_name,
            distinct_id=self.context.distinct_id,
            properties=properties,
            groups={
                "organization": self.context.organization_id,
                "project": self.context.team_uuid,
            },
        )
        await workflow.execute_activity(
            track_workflow_event,
            track_input,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

    async def _update_task_run_status(self, status: str, error_message: Optional[str] = None) -> None:
        await workflow.execute_activity(
            update_task_run_status,
            UpdateTaskRunStatusInput(
                run_id=self.context.run_id,
                status=status,
                error_message=error_message,
            ),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _relay_sandbox_events(
        self, agent_server_output: StartAgentServerOutput, sandbox_id: str | None = None
    ) -> None:
        """Start the SSE relay activity as a concurrent task (best-effort)."""
        try:
            relay_input = RelaySandboxEventsInput(
                run_id=self.context.run_id,
                task_id=self.context.task_id,
                sandbox_url=agent_server_output.sandbox_url,
                sandbox_connect_token=agent_server_output.connect_token,
                team_id=self.context.team_id,
                distinct_id=self.context.distinct_id,
                sandbox_id=sandbox_id,
            )
            await workflow.execute_activity(
                relay_sandbox_events,
                relay_input,
                start_to_close_timeout=timedelta(minutes=65),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=1),
                cancellation_type=workflow.ActivityCancellationType.TRY_CANCEL,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            workflow.logger.warning(
                "relay_sandbox_events_failed_non_fatal",
                run_id=self.context.run_id,
                error=str(e),
            )

    @staticmethod
    async def _cancel_relay(relay_task: "asyncio.Task[None]") -> None:
        """Cancel the relay task if still running."""
        if relay_task.done():
            return
        relay_task.cancel()
        try:
            await relay_task
        except (asyncio.CancelledError, Exception):
            pass

    async def _create_resume_snapshot(self, sandbox_id: str) -> None:
        """Create a filesystem snapshot for interactive sandbox resume."""
        try:
            result = await workflow.execute_activity(
                create_resume_snapshot,
                CreateResumeSnapshotInput(sandbox_id=sandbox_id, run_id=self.context.run_id),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            if result.external_id:
                workflow.logger.info(f"Resume snapshot created: {result.external_id} for sandbox {sandbox_id}")
            elif result.error:
                workflow.logger.warning(f"Resume snapshot skipped: {result.error}")
        except Exception as e:
            workflow.logger.warning(f"Resume snapshot failed (non-fatal): {e}")

    async def _trigger_snapshot_workflow(self) -> None:
        github_integration_id = self.context.github_integration_id
        repository = self.context.repository
        if github_integration_id is None or repository is None:
            workflow.logger.info("Skipping snapshot workflow — no repository configured")
            return

        workflow_id = f"create-snapshot-for-repository-{github_integration_id}-{repository.replace('/', '-')}"

        await workflow.start_child_workflow(
            workflow="create-snapshot-for-repository",
            arg=CreateSnapshotForRepositoryInput(
                github_integration_id=github_integration_id,
                repository=repository,
                team_id=self.context.team_id,
            ),
            id=workflow_id,
            task_queue=settings.TASKS_TASK_QUEUE,
            parent_close_policy=ParentClosePolicy.ABANDON,  # This will allow the snapshot workflow to continue even if the task workflow fails or closes
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

    async def _post_slack_update(self, sandbox_cleaned: bool = False) -> None:
        if not self._slack_thread_context:
            return
        await workflow.execute_activity(
            post_slack_update,
            PostSlackUpdateInput(
                run_id=self.context.run_id,
                slack_thread_context=self._slack_thread_context,
                sandbox_cleaned=sandbox_cleaned,
            ),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

    @temporalio.workflow.signal
    async def complete_task(self, status: str = "completed", error_message: Optional[str] = None) -> None:
        self._completion_status = status
        self._completion_error = error_message
        self._task_completed = True

    @temporalio.workflow.signal
    async def heartbeat(self) -> None:
        self._heartbeat_received = True

    @temporalio.workflow.signal
    async def send_followup_message(self, message: str) -> None:
        self._pending_followup = message

    async def _send_followup_to_sandbox(self, message: str) -> None:
        try:
            await workflow.execute_activity(
                send_followup_to_sandbox,
                SendFollowupToSandboxInput(run_id=self.context.run_id, message=message),
                start_to_close_timeout=timedelta(minutes=35),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except Exception as e:
            workflow.logger.warning(
                "send_followup_to_sandbox_failed",
                run_id=self.context.run_id,
                error=str(e),
            )
            # Mark the run as failed so _poll_for_turn sees a terminal status
            # immediately instead of waiting for the inactivity timeout.
            self._completion_status = "failed"
            self._completion_error = f"Follow-up delivery failed: {e}"
            self._task_completed = True
