import uuid
from datetime import timedelta

import pytest
import time_machine
from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from django.utils import timezone

from asgiref.sync import async_to_sync
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.temporal.models import ScheduledRecalculationStartResult
from products.experiments.backend.temporal.scheduled_recalculation_activities import (
    discover_scheduled_recalculation_candidates,
)
from products.experiments.backend.temporal.scheduled_recalculation_logic import (
    ScheduledRecalculationCandidate,
    ScheduledRecalculationDiscovery,
)
from products.experiments.backend.temporal.scheduled_recalculation_workflow import (
    ScheduledExperimentRecalculationWorkflow,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag


def _candidates(*experiment_ids: int) -> list[ScheduledRecalculationCandidate]:
    return [
        ScheduledRecalculationCandidate(experiment_id=eid, team_id=1, organization_id="org") for eid in experiment_ids
    ]


async def _run(discover, exposures, start, hour: int = 2) -> dict:
    @activity.defn(name="discover_scheduled_recalculation_candidates")
    async def discover_activity() -> ScheduledRecalculationDiscovery:
        return ScheduledRecalculationDiscovery(hour=hour, candidates=discover(hour))

    return await _execute(discover_activity, exposures, start)


async def _execute(discover_activity, exposures, start) -> dict:
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
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )


@pytest.mark.asyncio
async def test_no_candidates_returns_zeroes():
    result = await _run(lambda hour: [], lambda eid: True, lambda eid: None)
    assert result == {"hour": 2, "candidates": 0, "started": 0, "skipped": 0}


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_exposure_gate_stops_the_start_activity():
    started: list[int] = []

    def start(experiment_id: int) -> ScheduledRecalculationStartResult:
        started.append(experiment_id)
        return ScheduledRecalculationStartResult(experiment_id=experiment_id, started=True)

    result = await _run(lambda hour: _candidates(1, 2), lambda eid: eid == 1, start)
    assert started == [1]
    assert result["started"] == 1
    assert result["skipped"] == 1


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_discovery_failure_fails_the_workflow():
    def discover(hour: int) -> list[ScheduledRecalculationCandidate]:
        raise RuntimeError("postgres is down")

    with pytest.raises(WorkflowFailureError):
        await _run(discover, lambda eid: True, lambda eid: None)


# Non-atomic, because the real discovery activity reads from a worker thread that cannot see
# an uncommitted test transaction.
@time_machine.travel("2026-09-15T02:30:00Z", tick=True)
class TestScheduledRecalculationWorkflowDiscovery(NonAtomicBaseTest):
    def _experiment(self, rollout_percentage: int) -> Experiment:
        flag = FeatureFlag.objects.create(
            team=self.team,
            key=f"flag-{uuid.uuid4()}",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": rollout_percentage}]},
        )
        return Experiment.objects.create(
            team=self.team,
            name="exp",
            feature_flag=flag,
            start_date=timezone.now() - timedelta(days=2),
            metrics=[{"kind": "ExperimentMetric", "metric_type": "mean", "uuid": str(uuid.uuid4())}],
        )

    def test_a_skipped_experiment_never_reaches_the_exposure_check(self):
        candidate = self._experiment(rollout_percentage=100)
        self._experiment(rollout_percentage=0)
        checked: list[int] = []

        def exposures(experiment_id: int) -> bool:
            checked.append(experiment_id)
            return False

        with (
            patch(
                "products.experiments.backend.temporal.scheduled_recalculation_logic.feature_enabled_or_false",
                return_value=True,
            ),
            patch("products.experiments.backend.temporal.scheduled_recalculation_activities.posthoganalytics"),
        ):
            result = async_to_sync(_execute)(discover_scheduled_recalculation_candidates, exposures, lambda eid: None)
        assert checked == [candidate.id]
        assert result["candidates"] == 1
