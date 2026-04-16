import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from temporalio import activity
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.provision_sandbox import (
    CreateSandboxForRepositoryOutput,
    PrepareSandboxForRepositoryOutput,
)
from products.tasks.backend.temporal.process_task.activities.start_agent_server import StartAgentServerOutput
from products.tasks.backend.temporal.process_task.activities.update_task_run_status import UpdateTaskRunStatusInput
from products.tasks.backend.temporal.process_task.workflow import ProcessTaskInput, ProcessTaskWorkflow

_status_updates: list[tuple[str, str | None]] = []


@activity.defn(name="get_task_processing_context")
def _mock_get_context(_input) -> TaskProcessingContext:
    return TaskProcessingContext(
        task_id="task-1",
        run_id="run-1",
        team_id=1,
        team_uuid=str(uuid.uuid4()),
        organization_id=str(uuid.uuid4()),
        github_integration_id=1,
        repository="org/repo",
        distinct_id="user-1",
    )


@activity.defn(name="update_task_run_status")
def _mock_update_status(input: UpdateTaskRunStatusInput) -> None:
    _status_updates.append((input.status, input.error_message))


@activity.defn(name="prepare_sandbox_for_repository")
def _mock_prepare_sandbox(_input) -> PrepareSandboxForRepositoryOutput:
    return PrepareSandboxForRepositoryOutput(
        sandbox_name="sandbox-name",
        repository="org/repo",
        github_token="",
        branch=None,
        environment_variables={},
        snapshot_id=None,
        snapshot_external_id=None,
        used_snapshot=False,
        should_create_snapshot=False,
        shallow_clone=True,
        image_source="base_image",
        image_source_label="published sandbox base image",
    )


@activity.defn(name="create_sandbox_for_repository")
def _mock_create_sandbox(_input) -> CreateSandboxForRepositoryOutput:
    return CreateSandboxForRepositoryOutput(
        sandbox_id="sb-1",
        sandbox_url="http://localhost",
        connect_token=None,
    )


@activity.defn(name="clone_repository_in_sandbox")
def _mock_clone_repository(_input) -> None:
    pass


@activity.defn(name="start_agent_server")
def _mock_start_agent(_input) -> StartAgentServerOutput:
    return StartAgentServerOutput(sandbox_url="http://localhost")


@activity.defn(name="forward_pending_user_message")
def _mock_forward(_input) -> None:
    pass


@activity.defn(name="send_followup_to_sandbox")
def _mock_send_followup_raises(_input) -> None:
    raise RuntimeError("Sandbox session is dead")


@activity.defn(name="track_workflow_event")
def _mock_track(_input) -> None:
    pass


@activity.defn(name="read_sandbox_logs")
def _mock_read_logs(_input) -> str:
    return ""


@activity.defn(name="cleanup_sandbox")
def _mock_cleanup(_input) -> None:
    pass


pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


class TestFollowupDeliveryFailure:
    @pytest.mark.timeout(30)
    async def test_failed_followup_marks_run_as_failed_promptly(self):
        """The workflow must exit its main loop and mark the run as failed
        within seconds when a followup delivery fails — not after the
        5-minute inactivity timeout."""
        _status_updates.clear()

        async with await WorkflowEnvironment.start_time_skipping() as env:
            task_queue = f"test-{uuid.uuid4()}"
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[ProcessTaskWorkflow],
                activities=[
                    _mock_get_context,
                    _mock_update_status,
                    _mock_prepare_sandbox,
                    _mock_create_sandbox,
                    _mock_clone_repository,
                    _mock_start_agent,
                    _mock_forward,
                    _mock_send_followup_raises,
                    _mock_track,
                    _mock_read_logs,
                    _mock_cleanup,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=5),
            ):
                handle = await env.client.start_workflow(
                    ProcessTaskWorkflow.run,
                    ProcessTaskInput(run_id="run-1"),
                    id=f"test-{uuid.uuid4()}",
                    task_queue=task_queue,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=timedelta(minutes=2),
                )

                # Let setup activities complete before signaling
                await asyncio.sleep(2)

                await handle.signal(ProcessTaskWorkflow.send_followup_message, "test followup")

                result = await handle.result()

        assert result.success is True

        failed_updates = [(s, e) for s, e in _status_updates if s == "failed"]
        assert len(failed_updates) == 1
        assert "Follow-up delivery failed" in (failed_updates[0][1] or "")
