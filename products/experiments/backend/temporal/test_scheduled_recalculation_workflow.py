import uuid

import pytest

from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.experiments.backend.temporal.models import (
    ScheduledRecalculationStartResult,
    ScheduledRecalculationWorkflowInputs,
)
from products.experiments.backend.temporal.scheduled_recalculation_logic import ScheduledRecalculationCandidate
from products.experiments.backend.temporal.scheduled_recalculation_workflow import (
    ScheduledExperimentRecalculationWorkflow,
)

pytestmark = pytest.mark.asyncio


def _candidates(*experiment_ids: int) -> list[ScheduledRecalculationCandidate]:
    return [
        ScheduledRecalculationCandidate(experiment_id=eid, team_id=1, organization_id="org") for eid in experiment_ids
    ]


async def _run(discover, exposures, start, hour: int = 2) -> dict:
    @activity.defn(name="discover_scheduled_recalculation_candidates")
    async def discover_activity(hour: int) -> list[ScheduledRecalculationCandidate]:
        return discover(hour)

    @activity.defn(name="check_experiment_exposures")
    async def exposures_activity(experiment_id: int, hour: int) -> bool:
        return exposures(experiment_id)

    @activity.defn(name="start_scheduled_recalculation")
    async def start_activity(experiment_id: int, hour: int) -> ScheduledRecalculationStartResult:
        return start(experiment_id)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        task_queue = f"test-{uuid.uuid4()}"
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[ScheduledExperimentRecalculationWorkflow],
            activities=[discover_activity, exposures_activity, start_activity],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            return await env.client.execute_workflow(
                ScheduledExperimentRecalculationWorkflow.run,
                ScheduledRecalculationWorkflowInputs(hour=hour),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )


async def test_no_candidates_returns_zeroes():
    result = await _run(lambda hour: [], lambda eid: True, lambda eid: None)
    assert result == {"hour": 2, "candidates": 0, "started": 0, "skipped": 0}


async def test_every_candidate_starts():
    started: list[int] = []

    def start(experiment_id: int) -> ScheduledRecalculationStartResult:
        started.append(experiment_id)
        return ScheduledRecalculationStartResult(
            experiment_id=experiment_id, started=True, recalculation_id=str(uuid.uuid4())
        )

    result = await _run(lambda hour: _candidates(1, 2, 3), lambda eid: True, start)
    assert result["candidates"] == 3
    assert result["started"] == 3
    assert result["skipped"] == 0
    assert sorted(started) == [1, 2, 3]


async def test_exposure_gate_stops_the_start_activity():
    started: list[int] = []

    def start(experiment_id: int) -> ScheduledRecalculationStartResult:
        started.append(experiment_id)
        return ScheduledRecalculationStartResult(experiment_id=experiment_id, started=True)

    result = await _run(lambda hour: _candidates(1, 2), lambda eid: eid == 1, start)
    assert started == [1]
    assert result["started"] == 1
    assert result["skipped"] == 1


async def test_one_failing_candidate_does_not_stop_the_others():
    def exposures(experiment_id: int) -> bool:
        if experiment_id == 2:
            raise RuntimeError("boom")
        return True

    result = await _run(
        lambda hour: _candidates(1, 2, 3),
        exposures,
        lambda eid: ScheduledRecalculationStartResult(experiment_id=eid, started=True),
    )
    assert result["started"] == 2
    assert result["skipped"] == 1


async def test_discovery_failure_fails_the_workflow():
    def discover(hour: int) -> list[ScheduledRecalculationCandidate]:
        raise RuntimeError("postgres is down")

    with pytest.raises(WorkflowFailureError):
        await _run(discover, lambda eid: True, lambda eid: None)
