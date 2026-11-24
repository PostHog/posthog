import uuid
import asyncio
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from django.utils import timezone

import temporalio.workflow
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
    CALC_BUDGET_PATCH,
    RUN_START_WINDOW,
    RUN_WAIT_TIMEOUT,
    SCHEDULE_INTERVAL,
    SCHEDULED_CALC_BUDGET,
    START_ACTIVITY_MAX_ATTEMPTS,
    START_ACTIVITY_TIMEOUT,
    ScheduledExperimentRecalculationWorkflow,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag

WORKFLOW_MODULE = "products.experiments.backend.temporal.scheduled_recalculation_workflow"


def _candidates(*experiment_ids: int, metric_count: int | None = 1) -> list[ScheduledRecalculationCandidate]:
    return [
        ScheduledRecalculationCandidate(experiment_id=eid, team_id=1, organization_id="org", metric_count=metric_count)
        for eid in experiment_ids
    ]


async def _no_wait(recalculation_id: str) -> None:
    return None


def _started(experiment_id: int) -> ScheduledRecalculationStartResult:
    return ScheduledRecalculationStartResult(
        experiment_id=experiment_id, started=True, recalculation_id=str(uuid.uuid4())
    )


async def _run(
    discover, exposures, start, hour: int = 2, wait=_no_wait, replay_legacy=False, missing_patch: str | None = None
) -> dict:
    @activity.defn(name="discover_scheduled_recalculation_candidates")
    async def discover_activity() -> ScheduledRecalculationDiscovery:
        return ScheduledRecalculationDiscovery(hour=hour, candidates=discover(hour))

    return await _execute(
        discover_activity, exposures, start, wait, replay_legacy=replay_legacy, missing_patch=missing_patch
    )


def _patches(replay_legacy: bool, missing_patch: str | None):
    if replay_legacy:
        return patch(f"{WORKFLOW_MODULE}.temporalio.workflow.patched", return_value=False)
    if missing_patch is not None:
        patched = temporalio.workflow.patched
        return patch(
            f"{WORKFLOW_MODULE}.temporalio.workflow.patched",
            side_effect=lambda patch_id: patch_id != missing_patch and patched(patch_id),
        )
    return nullcontext()


async def _execute(
    discover_activity, exposures, start, wait=_no_wait, replay_legacy=False, missing_patch: str | None = None
) -> dict:
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
            with _patches(replay_legacy, missing_patch):
                handle = await env.client.start_workflow(
                    ScheduledExperimentRecalculationWorkflow.run,
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                    execution_timeout=SCHEDULE_INTERVAL,
                )
                result = await handle.result()
                history = await handle.fetch_history()
    if replay_legacy or missing_patch is not None:
        markers = sum(1 for event in history.events if event.HasField("marker_recorded_event_attributes"))
        assert markers == (0 if replay_legacy else 1)
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
@pytest.mark.parametrize(
    "metric_counts, missing_patch, peak_runs, peak_calcs",
    [
        pytest.param([3] * 6, None, 2, 6, id="calc_budget_binds"),
        pytest.param([1] * 6, None, 3, 3, id="run_cap_binds"),
        pytest.param([1, 9, 1], None, 1, 6, id="run_over_the_budget_starts_alone"),
        pytest.param([1, None, 1], None, 1, 6, id="unknown_count_starts_alone"),
        pytest.param([3] * 6, CALC_BUDGET_PATCH, 6, 18, id="history_before_the_calc_budget"),
    ],
)
async def test_admission_limits_runs_and_calcs_in_flight(metric_counts, missing_patch, peak_runs, peak_calcs):
    candidates = [
        ScheduledRecalculationCandidate(experiment_id=eid, team_id=1, organization_id="org", metric_count=count)
        for eid, count in enumerate(metric_counts, start=1)
    ]
    weights = {c.experiment_id: min(c.metric_count or SCHEDULED_CALC_BUDGET, SCHEDULED_CALC_BUDGET) for c in candidates}
    in_flight: dict[str, int] = {}
    peaks = {"runs": 0, "calcs": 0}
    peak_reached = asyncio.Event()

    def start(experiment_id: int) -> ScheduledRecalculationStartResult:
        result = _started(experiment_id)
        assert result.recalculation_id is not None
        in_flight[result.recalculation_id] = weights[experiment_id]
        peaks["runs"] = max(peaks["runs"], len(in_flight))
        peaks["calcs"] = max(peaks["calcs"], sum(in_flight.values()))
        # A peak of one never sets the event, so each run holds for the whole timeout and a second
        # admission beside it would raise the peak.
        if peak_runs > 1 and len(in_flight) == peak_runs:
            peak_reached.set()
        return result

    async def wait(recalculation_id: str) -> None:
        try:
            await asyncio.wait_for(peak_reached.wait(), timeout=5 if peak_runs > 1 else 1)
        except TimeoutError:
            pass
        del in_flight[recalculation_id]

    result = await _run(lambda hour: candidates, lambda eid: True, start, wait=wait, missing_patch=missing_patch)

    assert result["started"] == len(candidates)
    assert peaks == {"runs": peak_runs, "calcs": peak_calcs}


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["no_exposures", "exposure_error", "not_started"])
async def test_a_candidate_that_does_not_start_frees_its_admission(outcome):
    started: list[int] = []

    def exposures(experiment_id: int) -> bool:
        if experiment_id == 1 and outcome == "exposure_error":
            raise RuntimeError("boom")
        return not (experiment_id == 1 and outcome == "no_exposures")

    def start(experiment_id: int) -> ScheduledRecalculationStartResult:
        if experiment_id == 1:
            return ScheduledRecalculationStartResult(experiment_id=experiment_id, started=False)
        started.append(experiment_id)
        return _started(experiment_id)

    with patch(f"{WORKFLOW_MODULE}.SCHEDULED_RUN_CAP", 1):
        result = await _run(lambda hour: _candidates(1, 2, metric_count=6), exposures, start)

    assert started == [2]
    assert result["started"] == 1


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
        patch(f"{WORKFLOW_MODULE}.SCHEDULED_RUN_CAP", 1),
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
