from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricsRecalculation,
    ExperimentSavedMetric,
    ExperimentToSavedMetric,
)
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.experiments.backend.temporal.models import ScheduledRecalculationStartResult
from products.experiments.backend.temporal.scheduled_recalculation_activities import (
    SKIPPED_EVENT,
    _check_experiment_exposures_sync,
    _discover_scheduled_recalculation_candidates_sync,
    _start_scheduled_recalculation_sync,
)
from products.experiments.backend.temporal.scheduled_recalculation_logic import (
    SKIP_ACTIVE_RUN,
    SKIP_DISPATCH_UNCERTAIN,
    SKIP_EXPOSURE_BACKOFF,
    SKIP_EXPOSURE_QUERY_FAILED,
    SKIP_INSUFFICIENT_EXPOSURES,
    SKIP_NO_METRICS,
    SKIP_RECENT_RUN,
    SKIP_START_WINDOW_ELAPSED,
    SKIP_ZERO_ROLLOUT,
    ScheduledRecalculationDiscovery,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag

MODULE = "products.experiments.backend.temporal.scheduled_recalculation_activities"
# The activity resolves these at call time from their own module, to break an import cycle.
RECALCULATION = "products.experiments.backend.recalculation"

# Unwrap the database_sync_to_async_pool decorator so the bodies run synchronously in the test
# transaction, matching test_recalculation_activities.py.
_check_exposures_raw = _check_experiment_exposures_sync.func  # type: ignore[attr-defined]
_start_recalculation_raw = _start_scheduled_recalculation_sync.func  # type: ignore[attr-defined]
_discover_raw = _discover_scheduled_recalculation_candidates_sync.func  # type: ignore[attr-defined]


def _check_exposures(experiment_id: int, hour: int) -> bool:
    # close_old_connections() would drop the connection this test's transaction runs on.
    with patch(f"{MODULE}.close_old_connections"):
        return _check_exposures_raw(experiment_id, hour)


def _start_recalculation(
    experiment_id: int, hour: int, start_before: datetime | None = None
) -> ScheduledRecalculationStartResult:
    with patch(f"{MODULE}.close_old_connections"):
        return _start_recalculation_raw(experiment_id, hour, start_before)


def _discover() -> ScheduledRecalculationDiscovery:
    with (
        patch(f"{MODULE}.close_old_connections"),
        patch(
            "products.experiments.backend.temporal.scheduled_recalculation_logic.feature_enabled_or_false",
            return_value=True,
        ),
    ):
        return _discover_raw()


def _metric() -> dict:
    return {"kind": "ExperimentMetric", "metric_type": "mean", "uuid": str(uuid4())}


@time_machine.travel("2026-09-15T12:00:00Z", tick=False)
class TestScheduledRecalculationActivities(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        # Discovery selects the teams configured for the current hour, and the class clock is at 12:00.
        TeamExperimentsConfig.objects.update_or_create(
            team=self.team, defaults={"experiment_recalculation_times": ["12:00:00"]}
        )
        self.experiment = self._experiment()

    def _experiment(self, **overrides: object) -> Experiment:
        flag = FeatureFlag.objects.create(
            team=self.team,
            key=f"flag-{uuid4()}",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        defaults: dict = {
            "team": self.team,
            "name": "exp",
            "feature_flag": flag,
            "created_by": self.user,
            "start_date": timezone.now() - timedelta(days=2),
            "metrics": [_metric()],
        }
        return Experiment.objects.create(**{**defaults, **overrides})

    def _add_run(self, experiment: Experiment, **fields: object) -> None:
        with team_scope(self.team.id, canonical=True):
            ExperimentMetricsRecalculation.objects.create(team=self.team, experiment=experiment, **fields)

    def _zero_rollout(self) -> Experiment:
        experiment = self._experiment()
        experiment.feature_flag.filters = {"groups": [{"properties": [], "rollout_percentage": 0}]}
        experiment.feature_flag.save()
        return experiment

    def _active_run(self) -> Experiment:
        experiment = self._experiment()
        self._add_run(experiment, status=ExperimentMetricsRecalculation.Status.IN_PROGRESS, started_at=timezone.now())
        return experiment

    def _recent_run(self) -> Experiment:
        experiment = self._experiment()
        saved = ExperimentSavedMetric.objects.create(team=self.team, name="saved", query=_metric())
        ExperimentToSavedMetric.objects.create(experiment=experiment, saved_metric=saved)
        self._add_run(
            experiment,
            status=ExperimentMetricsRecalculation.Status.COMPLETED,
            completed_at=timezone.now() - timedelta(minutes=5),
        )
        return experiment

    @parameterized.expand(
        [
            ("zero_rollout", lambda test: test._zero_rollout(), SKIP_ZERO_ROLLOUT),
            ("no_metrics", lambda test: test._experiment(metrics=[]), SKIP_NO_METRICS),
            ("active_run", lambda test: test._active_run(), SKIP_ACTIVE_RUN),
            ("recent_run", lambda test: test._recent_run(), SKIP_RECENT_RUN),
        ]
    )
    def test_discovery_sends_a_skipped_event_instead_of_returning_the_experiment(
        self, _name: str, arrange: Callable[["TestScheduledRecalculationActivities"], Experiment], reason: str
    ):
        skipped = arrange(self)
        with patch(f"{MODULE}.posthoganalytics.capture") as capture:
            discovery = _discover()
        assert [c.experiment_id for c in discovery.candidates] == [self.experiment.id]
        capture.assert_called_once()
        assert capture.call_args.kwargs["event"] == SKIPPED_EVENT
        assert capture.call_args.kwargs["properties"]["experiment_id"] == skipped.id
        assert capture.call_args.kwargs["properties"]["reason"] == reason
        assert capture.call_args.kwargs["properties"]["hour"] == 12

    def test_discovery_query_count_does_not_grow_with_skips(self):
        # Covers the skipped events too: each one reads the team, organization and creator.
        def discovery_queries() -> int:
            with patch(f"{MODULE}.posthoganalytics.capture"), CaptureQueriesContext(connection) as queries:
                _discover()
            return len(queries.captured_queries)

        self._recent_run()
        baseline = discovery_queries()
        for _ in range(5):
            self._recent_run()
            self._zero_rollout()
        assert discovery_queries() == baseline

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

    @parameterized.expand(
        [
            ("three_insufficient", [0, 12, 49], 3),
            ("two_insufficient", [0, 0], None),
            ("reset_at_threshold", [0, 0, 50, 0], None),
            ("failed_query_keeps_the_count", [0, 0, RuntimeError("clickhouse is sad"), 0], 3),
            ("failed_query_adds_nothing", [0, 0, RuntimeError("clickhouse is sad")], None),
        ]
    )
    def test_consecutive_insufficient_checks_back_off_the_experiment(
        self, _name: str, outcomes: list[int | Exception], backed_off_count: int | None
    ):
        for outcome in outcomes:
            with (
                patch(f"{MODULE}.count_total_exposures", side_effect=[outcome]),
                patch(f"{MODULE}.posthoganalytics.capture"),
            ):
                _check_exposures(self.experiment.id, 12)
        with patch(f"{MODULE}.posthoganalytics.capture") as capture:
            discovery = _discover()
        if backed_off_count is None:
            assert [c.experiment_id for c in discovery.candidates] == [self.experiment.id]
            capture.assert_not_called()
            return
        assert discovery.candidates == []
        properties = capture.call_args.kwargs["properties"]
        assert capture.call_args.kwargs["event"] == SKIPPED_EVENT
        assert properties["reason"] == SKIP_EXPOSURE_BACKOFF
        assert properties["consecutive_insufficient_checks"] == backed_off_count
        assert properties["days_since_last_check"] == 0

    @parameterized.expand([("enough", 120, True), ("insufficient", 12, False)])
    def test_exposure_gate_ignores_a_redis_failure(self, _name: str, total: int, expected: bool):
        with (
            patch(f"{MODULE}.count_total_exposures", return_value=total),
            patch(f"{MODULE}.capture_skip"),
            patch(
                "products.experiments.backend.temporal.scheduled_recalculation_logic.get_client",
                side_effect=ConnectionError("redis down"),
            ),
        ):
            assert _check_exposures(self.experiment.id, 12) is expected

    @parameterized.expand([("legacy", False), ("within_deadline", True)])
    def test_start_creates_a_row_and_dispatches_the_workflow(self, _name: str, with_deadline: bool):
        with patch(f"{RECALCULATION}.start_metrics_recalculation_workflow") as dispatch:
            result = _start_recalculation(
                self.experiment.id, 2, timezone.now() + timedelta(minutes=1) if with_deadline else None
            )
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
        assert result.skip_reason == SKIP_DISPATCH_UNCERTAIN
        assert result.recalculation_id is not None
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


@pytest.mark.parametrize("seconds_late", [0, 60])
def test_start_picked_up_after_deadline_does_not_create_a_run(seconds_late):
    deadline = datetime(2026, 10, 19, 6, 50, tzinfo=UTC)
    with (
        time_machine.travel(deadline + timedelta(seconds=seconds_late), tick=False),
        patch(f"{MODULE}.close_old_connections"),
        patch(f"{RECALCULATION}.request_recalculation") as request,
        patch(f"{RECALCULATION}.start_metrics_recalculation_workflow") as dispatch,
    ):
        result = _start_recalculation_raw(1, 2, deadline)
    assert result.started is False
    assert result.skip_reason == SKIP_START_WINDOW_ELAPSED
    request.assert_not_called()
    dispatch.assert_not_called()
