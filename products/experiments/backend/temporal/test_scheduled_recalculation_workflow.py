import uuid
import asyncio
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from django.utils import timezone

from asgiref.sync import async_to_sync
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker

from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.recalculation import _STALE_RECALC_THRESHOLD
from products.experiments.backend.temporal.models import ScheduledRecalculationStartResult
from products.experiments.backend.temporal.scheduled_recalculation_activities import (
    discover_scheduled_recalculation_candidates,
)
from products.experiments.backend.temporal.scheduled_recalculation_logic import (
    SKIP_DISPATCH_UNCERTAIN,
    ScheduledRecalculationCandidate,
    ScheduledRecalculationDiscovery,
)
from products.experiments.backend.temporal.scheduled_recalculation_workflow import (
    RUN_START_WINDOW,
    RUN_WAIT_TIMEOUT,
    SCHEDULE_INTERVAL,
    START_ACTIVITY_MAX_ATTEMPTS,
    START_ACTIVITY_TIMEOUT,
    ScheduledExperimentRecalculationWorkflow,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag

WORKFLOW_MODULE = "products.experiments.backend.temporal.scheduled_recalculation_workflow"


def _candidates(*experiment_ids: int) -> list[ScheduledRecalculationCandidate]:
    return [
        ScheduledRecalculationCandidate(experiment_id=eid, team_id=1, organization_id="org") for eid in experiment_ids
    ]


async def _no_wait(recalculation_id: str) -> None:
    return None


def _started(experiment_id: int) -> ScheduledRecalculationStartResult:
    return ScheduledRecalculationStartResult(
        experiment_id=experiment_id, started=True, recalculation_id=str(uuid.uuid4())
    )


async def _run(discover, exposures, start, hour: int = 2, wait=_no_wait, replay_legacy=False) -> dict:
    @activity.defn(name="discover_scheduled_recalculation_candidates")
    async def discover_activity() -> ScheduledRecalculationDiscovery:
        return ScheduledRecalculationDiscovery(hour=hour, candidates=discover(hour))

    return await _execute(discover_activity, exposures, start, wait, replay_legacy=replay_legacy)


async def _execute(discover_activity, exposures, start, wait=_no_wait, replay_legacy=False) -> dict:
    @activity.defn(name="check_experiment_exposures")
    async def exposures_activity(experiment_id: int, hour: int) -> bool:
        return exposures(experiment_id)

    @activity.defn(name="start_scheduled_recalculation")
    async def start_activity(
        experiment_id: int, hour: int, start_before: datetime | None = None
    ) -> ScheduledRecalculationStartResult:
        return start(experiment_id)

    @activity.defn(name="wait_for_scheduled_recalculation")
    async def wait_activity(recalculation_id: str) -> None:
        await wait(recalculation_id)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        task_queue = f"test-{uuid.uuid4()}"
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[ScheduledExperimentRecalculationWorkflow],
            activities=[discover_activity, exposures_activity, start_activity, wait_activity],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with (
                patch(f"{WORKFLOW_MODULE}.temporalio.workflow.patched", return_value=False)
                if replay_legacy
                else nullcontext(),
            ):
                handle = await env.client.start_workflow(
                    ScheduledExperimentRecalculationWorkflow.run,
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                    execution_timeout=SCHEDULE_INTERVAL,
                )
                result = await handle.result()
                history = await handle.fetch_history()
    if replay_legacy:
        assert not any(event.HasField("marker_recorded_event_attributes") for event in history.events)
        await Replayer(
            workflows=[ScheduledExperimentRecalculationWorkflow], workflow_runner=UnsandboxedWorkflowRunner()
        ).replay_workflow(history)
    return result


@pytest.mark.asyncio
async def test_no_candidates_returns_zeroes():
    result = await _run(lambda hour: [], lambda eid: True, lambda eid: None)
    assert result == {"hour": 2, "candidates": 0, "started": 0, "skipped": 0, "deferred": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize("replay_legacy", [False, True])
async def test_every_candidate_starts(replay_legacy):
    started: list[int] = []

    def start(experiment_id: int) -> ScheduledRecalculationStartResult:
        started.append(experiment_id)
        return ScheduledRecalculationStartResult(
            experiment_id=experiment_id, started=True, recalculation_id=str(uuid.uuid4())
        )

    result = await _run(lambda hour: _candidates(1, 2, 3), lambda eid: True, start, replay_legacy=replay_legacy)
    assert result["candidates"] == 3
    assert result["started"] == 3
    assert result["skipped"] == 0
    assert sorted(started) == [1, 2, 3]


@pytest.mark.asyncio
async def test_runs_in_flight_never_exceed_the_cap():
    running = 0
    peak = 0

    def start(experiment_id: int) -> ScheduledRecalculationStartResult:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        return _started(experiment_id)

    async def wait(recalculation_id: str) -> None:
        nonlocal running
        await asyncio.sleep(0.01)
        running -= 1

    with patch(f"{WORKFLOW_MODULE}.MAX_CONCURRENT_EXPERIMENTS", 3):
        result = await _run(lambda hour: _candidates(*range(1, 13)), lambda eid: True, start, wait=wait)

    assert result["started"] == 12
    assert peak <= 3


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "wait", "start", "dispatch"])
async def test_experiments_left_after_the_start_window_are_deferred(failure):
    checked: list[int] = []
    started: list[int] = []

    def exposures(experiment_id: int) -> bool:
        checked.append(experiment_id)
        return True

    def start(experiment_id: int) -> ScheduledRecalculationStartResult:
        started.append(experiment_id)
        if failure == "start":
            raise ApplicationError("unknown dispatch outcome", non_retryable=True)
        if failure == "dispatch":
            return ScheduledRecalculationStartResult(
                experiment_id=experiment_id,
                started=False,
                recalculation_id=str(uuid.uuid4()),
                skip_reason=SKIP_DISPATCH_UNCERTAIN,
            )
        return _started(experiment_id)

    now = datetime(2026, 10, 18, 6, 30, tzinfo=UTC)

    async def wait(recalculation_id):
        nonlocal now
        if failure == "wait":
            raise ApplicationError("cannot observe run", non_retryable=True)
        now += RUN_START_WINDOW

    with (
        patch(f"{WORKFLOW_MODULE}.MAX_CONCURRENT_EXPERIMENTS", 1),
        patch(f"{WORKFLOW_MODULE}.temporalio.workflow.now", lambda: now),
    ):
        result = await _run(lambda hour: _candidates(1, 2, 3), exposures, start, wait=wait)

    assert checked == [1]
    assert started == [1]
    count = 0 if failure in ("start", "dispatch") else 1
    assert result == {"hour": 2, "candidates": 3, "started": count, "skipped": 3 - count, "deferred": 2}


@pytest.mark.asyncio
@pytest.mark.parametrize("delayed_activity", ["exposures", "start"])
async def test_retry_backoff_cannot_start_another_attempt_after_the_window(delayed_activity):
    attempts = []

    def delayed(experiment_id):
        attempts.append(experiment_id)
        raise ApplicationError("worker unavailable", next_retry_delay=RUN_START_WINDOW + timedelta(minutes=1))

    result = await _run(
        lambda hour: _candidates(1),
        delayed if delayed_activity == "exposures" else lambda eid: True,
        delayed if delayed_activity == "start" else _started,
    )
    assert result["started"] == 0
    assert result["skipped"] == 1
    assert attempts == [1]


def test_last_run_ends_before_the_next_hourly_firing():
    worst_case = RUN_START_WINDOW + START_ACTIVITY_TIMEOUT * START_ACTIVITY_MAX_ATTEMPTS + RUN_WAIT_TIMEOUT

    assert RUN_WAIT_TIMEOUT >= _STALE_RECALC_THRESHOLD
    assert worst_case < SCHEDULE_INTERVAL


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
    # The flush after each test deletes the team and user, so a pytest rerun or a second
    # test in this class needs them created again.
    CLASS_DATA_LEVEL_SETUP = False

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
