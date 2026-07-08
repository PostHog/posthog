import uuid

import pytest

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.pulse.backend.temporal.inputs import (
    GenerateBriefWorkflowInputs,
    MarkBriefFailedInputs,
    RunAgentInputs,
    SynthesizeActivityInputs,
    ValidatePersistInputs,
)
from products.pulse.backend.temporal.workflow import GenerateProductBriefWorkflow

pytestmark = pytest.mark.asyncio

BUNDLE = {"seed_items": [{"fingerprint_hint": "abc:0"}]}
QUIET_BUNDLE: dict = {"seed_items": []}


def _stub_activities(bundle: dict, calls: list[str]) -> list:
    @activity.defn(name="prepare_mission_activity")
    async def prepare_mission_activity(inputs: GenerateBriefWorkflowInputs) -> dict:
        calls.append("prepare")
        return bundle

    @activity.defn(name="run_agent_activity")
    async def run_agent_activity(inputs: RunAgentInputs) -> dict:
        calls.append("run_agent")
        return {"report": {}, "agent_session_ref": "sb-1", "transcript_key": None}

    @activity.defn(name="validate_and_persist_activity")
    async def validate_and_persist_activity(inputs: ValidatePersistInputs) -> str:
        calls.append("persist")
        return "ready"

    @activity.defn(name="mark_brief_quiet_activity")
    async def mark_brief_quiet_activity(inputs: MarkBriefFailedInputs) -> None:
        calls.append("quiet")

    @activity.defn(name="mark_brief_failed_activity")
    async def mark_brief_failed_activity(inputs: MarkBriefFailedInputs) -> None:
        calls.append("failed")

    @activity.defn(name="gather_brief_inputs_activity")
    async def gather_brief_inputs_activity(inputs: GenerateBriefWorkflowInputs) -> list[dict]:
        calls.append("gather")
        return []

    @activity.defn(name="synthesize_brief_activity")
    async def synthesize_brief_activity(inputs: SynthesizeActivityInputs) -> str:
        calls.append("synthesize")
        return "quiet"

    return [
        prepare_mission_activity,
        run_agent_activity,
        validate_and_persist_activity,
        mark_brief_quiet_activity,
        mark_brief_failed_activity,
        gather_brief_inputs_activity,
        synthesize_brief_activity,
    ]


async def _run(engine: str, bundle: dict) -> list[str]:
    calls: list[str] = []
    task_queue = f"test-pulse-{uuid.uuid4()}"
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[GenerateProductBriefWorkflow],
            activities=_stub_activities(bundle, calls),
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                GenerateProductBriefWorkflow.run,
                GenerateBriefWorkflowInputs(team_id=1, brief_id=str(uuid.uuid4()), engine=engine),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )
    return calls


async def test_agent_engine_runs_prepare_run_persist() -> None:
    assert await _run("agent", BUNDLE) == ["prepare", "run_agent", "persist"]


async def test_quiet_week_skips_the_agent_entirely() -> None:
    assert await _run("agent", QUIET_BUNDLE) == ["prepare", "quiet"]


async def test_synthesize_engine_path_is_unchanged() -> None:
    assert await _run("synthesize", BUNDLE) == ["gather", "synthesize"]
