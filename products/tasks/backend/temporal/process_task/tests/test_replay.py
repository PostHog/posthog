"""Replay guard for `ProcessTaskWorkflow`.

Temporal replays a running workflow's recorded history against the deployed definition, so a
change that adds, removes, or reorders a command fails every in-flight run with `[TMPRL1100]`.
The histories in `histories/` are recordings of runs the workflow has already produced, and CI
replays them against the current definition. A new command has to sit behind a
`workflow.patched` gate to keep them replayable.

Regenerate the recordings only for an intentional, gated change, and review the diff:

    TASKS_REPLAY_HISTORY_REGENERATE=1 hogli test products/tasks/backend/temporal/process_task/tests/test_replay.py

The `pre_patch` recording answers no for every patch id, which is the shape of a history written
before the current rollout — the one an in-flight run holds while a deploy lands.
"""

import os
import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import pytest

from temporalio import (
    activity,
    workflow as temporal_workflow,
)
from temporalio.client import WorkflowHistory
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker

from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.provision_sandbox import (
    CreateSandboxForRepositoryOutput,
    PrepareSandboxForRepositoryOutput,
)
from products.tasks.backend.temporal.process_task.activities.start_agent_server import StartAgentServerOutput
from products.tasks.backend.temporal.process_task.workflow import ProcessTaskInput, ProcessTaskWorkflow

HISTORY_DIR = Path(__file__).parent / "histories"
REGENERATE_ENV_VAR = "TASKS_REPLAY_HISTORY_REGENERATE"
BASE_INACTIVITY_SECONDS = 120

# Each case is one recorded run: the file under `histories/`, and whether its patch markers
# were recorded.
CASES = [("in_flight_turn", True), ("in_flight_turn_pre_patch", False)]


@activity.defn(name="get_task_processing_context")
def _mock_get_context(_input) -> TaskProcessingContext:
    return TaskProcessingContext(
        task_id="task-1",
        run_id="run-1",
        team_id=1,
        team_uuid="00000000-0000-0000-0000-000000000001",
        organization_id="00000000-0000-0000-0000-000000000002",
        github_integration_id=1,
        repository="org/repo",
        distinct_id="user-1",
        state={"inactivity_timeout_seconds": BASE_INACTIVITY_SECONDS},
    )


@activity.defn(name="update_task_run_status")
def _mock_update_status(_input) -> None:
    pass


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
    return CreateSandboxForRepositoryOutput(sandbox_id="sb-1", sandbox_url="http://localhost", connect_token=None)


@activity.defn(name="clone_repository_in_sandbox")
def _mock_clone_repository(_input) -> None:
    pass


@activity.defn(name="start_agent_server")
def _mock_start_agent(_input) -> StartAgentServerOutput:
    return StartAgentServerOutput(sandbox_url="http://localhost")


@activity.defn(name="forward_pending_user_message")
def _mock_forward(_input) -> None:
    pass


@activity.defn(name="emit_progress_activity")
def _mock_emit_progress(_input) -> None:
    pass


@activity.defn(name="track_workflow_event")
def _mock_track(_input) -> None:
    pass


@activity.defn(name="read_sandbox_logs")
def _mock_read_logs(_input) -> str:
    return ""


@activity.defn(name="cleanup_sandbox")
def _mock_cleanup(_input) -> None:
    pass


ACTIVITIES = [
    _mock_get_context,
    _mock_update_status,
    _mock_prepare_sandbox,
    _mock_create_sandbox,
    _mock_clone_repository,
    _mock_start_agent,
    _mock_forward,
    _mock_emit_progress,
    _mock_track,
    _mock_read_logs,
    _mock_cleanup,
]

pytestmark = pytest.mark.asyncio


class TestProcessTaskWorkflowReplay:
    @pytest.mark.parametrize("name", [name for name, _ in CASES])
    @pytest.mark.timeout(60, func_only=True)
    async def test_saved_history_replays_against_the_current_workflow(self, name: str):
        history = WorkflowHistory.from_json("process-task-replay", (HISTORY_DIR / f"{name}.json").read_text())

        await Replayer(
            workflows=[ProcessTaskWorkflow],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ).replay_workflow(history)


@pytest.mark.skipif(not os.environ.get(REGENERATE_ENV_VAR), reason=f"set {REGENERATE_ENV_VAR}=1 to re-record")
@pytest.mark.django_db
class TestRecordProcessTaskWorkflowHistories:
    @pytest.mark.parametrize("name, patches_recorded", CASES)
    @pytest.mark.timeout(120, func_only=True)
    async def test_record(self, monkeypatch, name: str, patches_recorded: bool):
        if not patches_recorded:
            monkeypatch.setattr(temporal_workflow, "patched", lambda _patch_id: False)

        async with await WorkflowEnvironment.start_time_skipping() as env:
            task_queue = f"test-{uuid.uuid4()}"
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[ProcessTaskWorkflow],
                activities=ACTIVITIES,
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=5),
            ):
                handle = await env.client.start_workflow(
                    ProcessTaskWorkflow.run,
                    ProcessTaskInput(run_id="run-1", create_pr=False),
                    id=f"test-{uuid.uuid4()}",
                    task_queue=task_queue,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=timedelta(hours=4),
                )
                await asyncio.sleep(2)
                # An active agent opens a turn, and the heartbeat ends the current wait, so the
                # loop arms its idle timer with the turn open — the state the in-flight idle
                # floor reads. The turn then ends and the run idles out.
                await handle.signal(ProcessTaskWorkflow.agent_state_changed, True)
                await handle.signal(ProcessTaskWorkflow.heartbeat, True)
                await asyncio.sleep(2)
                await handle.signal(ProcessTaskWorkflow.agent_state_changed, False)
                await env.sleep(timedelta(hours=1))
                await handle.result()
                history = await handle.fetch_history()

        HISTORY_DIR.mkdir(exist_ok=True)
        (HISTORY_DIR / f"{name}.json").write_text(history.to_json() + "\n")
