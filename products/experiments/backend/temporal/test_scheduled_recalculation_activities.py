from datetime import timedelta
from uuid import uuid4

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from posthog.models.scoping import team_scope

from products.experiments.backend.models.experiment import Experiment, ExperimentMetricsRecalculation
from products.experiments.backend.temporal.models import ScheduledRecalculationStartResult
from products.experiments.backend.temporal.scheduled_recalculation_activities import (
    _check_experiment_exposures_sync,
    _start_scheduled_recalculation_sync,
)
from products.experiments.backend.temporal.scheduled_recalculation_logic import (
    SKIP_ACTIVE_RUN,
    SKIP_EXPOSURE_QUERY_FAILED,
    SKIP_INSUFFICIENT_EXPOSURES,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag

MODULE = "products.experiments.backend.temporal.scheduled_recalculation_activities"
# The activity resolves these at call time from their own module, to break an import cycle.
RECALCULATION = "products.experiments.backend.recalculation"

# Unwrap the database_sync_to_async_pool decorator so the bodies run synchronously in the test
# transaction, matching test_recalculation_activities.py.
_check_exposures_raw = _check_experiment_exposures_sync.func  # type: ignore[attr-defined]
_start_recalculation_raw = _start_scheduled_recalculation_sync.func  # type: ignore[attr-defined]


def _check_exposures(experiment_id: int, hour: int) -> bool:
    # close_old_connections() would drop the connection this test's transaction runs on.
    with patch(f"{MODULE}.close_old_connections"):
        return _check_exposures_raw(experiment_id, hour)


def _start_recalculation(experiment_id: int, hour: int) -> ScheduledRecalculationStartResult:
    with patch(f"{MODULE}.close_old_connections"):
        return _start_recalculation_raw(experiment_id, hour)


@time_machine.travel("2026-09-15T12:00:00Z", tick=False)
class TestScheduledRecalculationActivities(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag = FeatureFlag.objects.create(
            team=self.team, key=f"flag-{uuid4()}", created_by=self.user, filters={"groups": []}
        )
        self.experiment = Experiment.objects.create(
            team=self.team,
            name="exp",
            feature_flag=flag,
            status=Experiment.Status.RUNNING,
            start_date=timezone.now() - timedelta(days=2),
            metrics=[{"kind": "ExperimentMetric", "metric_type": "mean", "uuid": str(uuid4())}],
        )

    def test_exposure_gate_passes_above_threshold(self):
        with patch(f"{MODULE}.count_total_exposures", return_value=120):
            assert _check_exposures(self.experiment.id, 2) is True

    def test_exposure_gate_fails_below_threshold(self):
        with patch(f"{MODULE}.count_total_exposures", return_value=12), patch(f"{MODULE}.capture_skip") as capture:
            assert _check_exposures(self.experiment.id, 2) is False
        assert capture.call_args.kwargs["reason"] == SKIP_INSUFFICIENT_EXPOSURES

    def test_exposure_query_failure_skips(self):
        with (
            patch(f"{MODULE}.count_total_exposures", side_effect=RuntimeError("clickhouse is sad")),
            patch(f"{MODULE}.capture_skip") as capture,
        ):
            assert _check_exposures(self.experiment.id, 2) is False
        assert capture.call_args.kwargs["reason"] == SKIP_EXPOSURE_QUERY_FAILED

    def test_start_creates_a_row_and_dispatches_the_workflow(self):
        with patch(f"{RECALCULATION}.start_metrics_recalculation_workflow") as dispatch:
            result = _start_recalculation(self.experiment.id, 2)
        assert result.started is True
        assert result.recalculation_id is not None
        with team_scope(self.team.id, canonical=True):
            recalc = ExperimentMetricsRecalculation.objects.get(id=result.recalculation_id)
        assert recalc.trigger == ExperimentMetricsRecalculation.Trigger.SCHEDULED
        assert recalc.created_by is None
        dispatch.assert_called_once_with(
            result.recalculation_id,
            team_id=self.team.id,
            organization_id=str(self.team.organization_id),
        )

    def test_start_skips_when_a_run_is_active(self):
        with team_scope(self.team.id, canonical=True):
            ExperimentMetricsRecalculation.objects.create(
                team=self.team,
                experiment=self.experiment,
                status=ExperimentMetricsRecalculation.Status.IN_PROGRESS,
                started_at=timezone.now(),
            )
        with patch(f"{RECALCULATION}.start_metrics_recalculation_workflow") as dispatch:
            result = _start_recalculation(self.experiment.id, 2)
        assert result.started is False
        assert result.skip_reason == SKIP_ACTIVE_RUN
        dispatch.assert_not_called()

    def test_start_skips_when_request_recalculation_reports_an_existing_run(self):
        with (
            patch(f"{RECALCULATION}.request_recalculation", return_value={"id": uuid4(), "is_existing": True}),
            patch(f"{RECALCULATION}.start_metrics_recalculation_workflow") as dispatch,
        ):
            result = _start_recalculation(self.experiment.id, 2)
        assert result.started is False
        assert result.skip_reason == SKIP_ACTIVE_RUN
        dispatch.assert_not_called()

    def test_start_reports_not_started_when_dispatch_fails(self):
        # The row rollback belongs to start_metrics_recalculation_workflow. What this activity owes
        # is an honest result: no started event for a workflow that never started.
        with (
            patch(f"{RECALCULATION}.start_metrics_recalculation_workflow", side_effect=RuntimeError("temporal down")),
            patch(f"{MODULE}.capture_started") as started_event,
        ):
            result = _start_recalculation(self.experiment.id, 2)
        assert result.started is False
        started_event.assert_not_called()

    def test_deleted_experiment_is_skipped_not_raised(self):
        missing_id = self.experiment.id + 10_000
        assert _check_exposures(missing_id, 2) is False
        result = _start_recalculation(missing_id, 2)
        assert result.started is False

    def test_start_skips_an_experiment_stopped_since_discovery(self):
        # Discovery runs before the exposure query, so the experiment can stop in between.
        self.experiment.end_date = timezone.now()
        self.experiment.save()
        with patch(f"{RECALCULATION}.start_metrics_recalculation_workflow") as dispatch:
            result = _start_recalculation(self.experiment.id, 2)
        assert result.started is False
        dispatch.assert_not_called()
