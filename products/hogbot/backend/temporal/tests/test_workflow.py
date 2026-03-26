import uuid
import asyncio

import pytest

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.hogbot.backend.temporal.activities import (
    CreateHogbotSandboxOutput,
    CreateResumeSnapshotOutput,
    PersistHogbotSnapshotInput,
    StartHogbotServerOutput,
    WaitForHogbotServerExitInput,
    WaitForHogbotServerExitOutput,
)
from products.hogbot.backend.temporal.workflow import HogbotWorkflow, HogbotWorkflowInput, HogbotWorkflowOutput

pytestmark = pytest.mark.asyncio


def _make_mock_activities(
    *,
    wait_output: WaitForHogbotServerExitOutput,
    release_server: asyncio.Event | None = None,
    snapshot_should_raise: bool = False,
):
    persisted_snapshots: list[PersistHogbotSnapshotInput] = []
    snapshot_calls = 0

    @activity.defn(name="create_hogbot_sandbox")
    async def mock_create_hogbot_sandbox(_input) -> CreateHogbotSandboxOutput:
        return CreateHogbotSandboxOutput(
            sandbox_id="sb-1",
            sandbox_url="http://sandbox",
            connect_token=None,
        )

    @activity.defn(name="start_hogbot_server")
    async def mock_start_hogbot_server(_input) -> StartHogbotServerOutput:
        return StartHogbotServerOutput(
            server_url="http://sandbox",
            connect_token=None,
        )

    @activity.defn(name="hogbot_create_resume_snapshot")
    async def mock_create_resume_snapshot(_input) -> CreateResumeSnapshotOutput:
        nonlocal snapshot_calls
        snapshot_calls += 1
        if snapshot_should_raise:
            raise AssertionError("create_resume_snapshot should not be called")
        return CreateResumeSnapshotOutput(external_id="snap-1", error=None)

    @activity.defn(name="persist_hogbot_snapshot")
    async def mock_persist_hogbot_snapshot(input: PersistHogbotSnapshotInput) -> None:
        persisted_snapshots.append(input)

    @activity.defn(name="wait_for_hogbot_server_exit")
    async def mock_wait_for_hogbot_server_exit(_input: WaitForHogbotServerExitInput) -> WaitForHogbotServerExitOutput:
        if release_server is not None:
            await release_server.wait()
        return wait_output

    @activity.defn(name="hogbot_read_sandbox_logs")
    async def mock_read_sandbox_logs(_input) -> str:
        return "ok"

    @activity.defn(name="hogbot_cleanup_sandbox")
    async def mock_cleanup_sandbox(_input) -> None:
        return None

    activities = [
        mock_create_hogbot_sandbox,
        mock_start_hogbot_server,
        mock_wait_for_hogbot_server_exit,
        mock_create_resume_snapshot,
        mock_persist_hogbot_snapshot,
        mock_read_sandbox_logs,
        mock_cleanup_sandbox,
    ]

    return activities, persisted_snapshots, lambda: snapshot_calls


async def _wait_for_ready_connection_info(handle) -> dict[str, object]:
    last_error: Exception | None = None

    for _ in range(20):
        try:
            info = await handle.query(HogbotWorkflow.get_connection_info)
        except Exception as e:
            last_error = e
        else:
            if info["ready"]:
                return info
        await asyncio.sleep(0)

    if last_error is not None:
        raise last_error
    raise AssertionError("Hogbot workflow never became ready")


async def test_hogbot_workflow_waits_for_server_exit_and_persists_snapshot():
    release_server = asyncio.Event()
    activities, persisted_snapshots, snapshot_call_count = _make_mock_activities(
        wait_output=WaitForHogbotServerExitOutput(status="completed", exit_code=0),
        release_server=release_server,
    )
    task_queue = f"test-hogbot-{uuid.uuid4()}"

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[HogbotWorkflow],
            activities=activities,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await env.client.start_workflow(
                HogbotWorkflow.run,
                HogbotWorkflowInput(team_id=1, server_command="python -m http.server 8080"),
                id=f"hogbot-team-{uuid.uuid4()}",
                task_queue=task_queue,
            )

            connection_info = await _wait_for_ready_connection_info(handle)
            assert connection_info["phase"] == "running"
            assert connection_info["server_url"] == "http://sandbox"

            release_server.set()

            result: HogbotWorkflowOutput = await handle.result()

    assert result.success is True
    assert result.snapshot_external_id == "snap-1"
    assert snapshot_call_count() == 1
    assert persisted_snapshots == [PersistHogbotSnapshotInput(team_id=1, snapshot_external_id="snap-1")]


async def test_hogbot_workflow_skips_snapshot_when_server_exits_with_error():
    activities, persisted_snapshots, snapshot_call_count = _make_mock_activities(
        wait_output=WaitForHogbotServerExitOutput(
            status="failed",
            exit_code=1,
            error="Hogbot server exited with code 1",
        ),
        snapshot_should_raise=True,
    )
    task_queue = f"test-hogbot-{uuid.uuid4()}"

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[HogbotWorkflow],
            activities=activities,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result: HogbotWorkflowOutput = await env.client.execute_workflow(
                HogbotWorkflow.run,
                HogbotWorkflowInput(
                    team_id=1,
                    server_command="python -m http.server 8080",
                ),
                id=f"hogbot-team-{uuid.uuid4()}",
                task_queue=task_queue,
            )

    assert result.success is False
    assert result.status == "failed"
    assert result.error is not None
    assert "code 1" in result.error
    assert snapshot_call_count() == 0
    assert persisted_snapshots == []
