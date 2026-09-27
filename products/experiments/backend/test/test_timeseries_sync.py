from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from products.experiments.backend.hogql_queries.experiment_metric_fingerprint import compute_metric_fingerprint
from products.experiments.backend.hogql_queries.utils import get_experiment_stats_method
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentMetricsRecalculation,
    ExperimentSavedMetric,
    ExperimentToSavedMetric,
)
from products.experiments.backend.recalculation import get_run_results
from products.experiments.backend.temporal.metric_resolution import find_metric_dict
from products.experiments.backend.temporal.recalc_fingerprint import compute_recalc_fingerprint
from products.experiments.backend.timeseries_sync import sync_timeseries_recalculation
from products.feature_flags.backend.models.feature_flag import FeatureFlag

RUN_STARTED_AT = datetime(2026, 3, 1, 2, 0, tzinfo=UTC)
IN_RUN = datetime(2026, 3, 1, 2, 7, tzinfo=UTC)
LATER_IN_RUN = datetime(2026, 3, 1, 2, 9, tzinfo=UTC)
BEFORE_RUN = datetime(2026, 2, 28, 2, 5, tzinfo=UTC)
IN_FUTURE = datetime(2026, 3, 3, 0, 0, tzinfo=UTC)


def _mean_metric(uuid: str) -> dict:
    return {
        "uuid": uuid,
        "kind": "ExperimentMetric",
        "metric_type": "mean",
        "source": {"kind": "EventsNode", "event": "purchase"},
    }


def _retention_metric(uuid: str) -> dict:
    return {
        "uuid": uuid,
        "kind": "ExperimentMetric",
        "metric_type": "retention",
        "start_event": {"kind": "EventsNode", "event": "signup"},
        "completion_event": {"kind": "EventsNode", "event": "purchase"},
    }


@pytest.mark.django_db(transaction=True)
@time_machine.travel("2026-03-01T02:10:00Z", tick=False)
class TestSyncTimeseriesRecalculation(BaseTest):
    def _experiment(self, flag_key: str, metrics: list[dict]) -> Experiment:
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key=flag_key,
            name=f"Flag for {flag_key}",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        exp = Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            feature_flag=flag,
            name="exp",
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
        )
        exp.metrics = metrics
        exp.save()
        return exp

    def _config_fp(self, exp: Experiment, metric_uuid: str) -> str:
        assert exp.start_date is not None
        metric_dict = find_metric_dict(exp, metric_uuid)
        assert metric_dict is not None
        return compute_metric_fingerprint(
            metric_dict,
            exp.start_date,
            get_experiment_stats_method(exp),
            exp.exposure_criteria,
            only_count_matured_users=exp.only_count_matured_users,
        )

    def _timeseries_point(self, exp: Experiment, metric_uuid: str, query_to: datetime, result: dict) -> None:
        assert exp.start_date is not None
        ExperimentMetricResult.objects.create(
            experiment=exp,
            metric_uuid=metric_uuid,
            fingerprint=self._config_fp(exp, metric_uuid),
            query_from=exp.start_date,
            query_to=query_to,
            status="completed",
            result=result,
        )

    def _sync(
        self,
        exp: Experiment,
        now: datetime = LATER_IN_RUN + timedelta(minutes=1),
        run_started_at: datetime = RUN_STARTED_AT,
    ) -> str | None:
        return sync_timeseries_recalculation(exp.id, team_id=self.team.id, run_started_at=run_started_at, now=now)

    def _link_saved_metric(self, exp: Experiment, metric_uuid: str) -> None:
        saved = ExperimentSavedMetric.objects.create(team=self.team, name=metric_uuid, query=_mean_metric(metric_uuid))
        ExperimentToSavedMetric.objects.create(experiment=exp, saved_metric=saved, metadata={"type": "primary"})

    def test_creates_a_completed_run_from_the_points_of_this_daily_run(self):
        exp = self._experiment("sync-full", [_mean_metric("m1"), _mean_metric("m2")])
        self._timeseries_point(exp, "m1", IN_RUN, {"m": 1})
        self._timeseries_point(exp, "m2", LATER_IN_RUN, {"m": 2})

        recalculation_id = self._sync(exp)

        assert recalculation_id is not None
        recalc = ExperimentMetricsRecalculation.objects.get(id=recalculation_id)
        assert recalc.status == ExperimentMetricsRecalculation.Status.COMPLETED
        assert recalc.trigger == ExperimentMetricsRecalculation.Trigger.TIMESERIES_SYNC
        assert recalc.total_metrics == 2
        assert recalc.metric_uuids == ["m1", "m2"]
        assert recalc.completed_at is not None
        # One second past the newest point, so the copies never collide with a timeseries row on the
        # (experiment, metric_uuid, query_to) key.
        assert recalc.query_to == LATER_IN_RUN + timedelta(seconds=1)

        results = {r["metric_uuid"]: r["result"] for r in get_run_results(recalc)}
        assert results == {"m1": {"m": 1}, "m2": {"m": 2}}
        copies = ExperimentMetricResult.objects.filter(experiment=exp, query_to=recalc.query_to)
        assert {row.fingerprint for row in copies} == {
            compute_recalc_fingerprint(self._config_fp(exp, "m1")),
            compute_recalc_fingerprint(self._config_fp(exp, "m2")),
        }
        # The timeseries rows keep their config fingerprint.
        assert ExperimentMetricResult.objects.filter(experiment=exp, fingerprint=self._config_fp(exp, "m1")).exists()

        # A second pass over the same run finds the new row already covers these points.
        assert self._sync(exp) is None
        assert ExperimentMetricsRecalculation.objects.filter(experiment=exp).count() == 1

    def test_finds_points_written_under_the_daily_saved_metric_fingerprint(self):
        """The daily saved-metrics discovery hashes the raw saved query, while the sync resolves the metric
        through find_metric_dict, which injects an empty breakdown list. The two must land on the same
        fingerprint, or every saved metric computes fresh points each morning that are never published."""
        exp = self._experiment("sync-saved", [])
        self._link_saved_metric(exp, "sm1")
        assert exp.start_date is not None

        saved_query = ExperimentSavedMetric.objects.get(team=self.team, name="sm1").query
        daily_fp = compute_metric_fingerprint(
            saved_query,
            exp.start_date,
            get_experiment_stats_method(exp),
            exp.exposure_criteria,
            only_count_matured_users=exp.only_count_matured_users,
            excluded_variants=exp.excluded_variants,
        )
        ExperimentMetricResult.objects.create(
            experiment=exp,
            metric_uuid="sm1",
            fingerprint=daily_fp,
            query_from=exp.start_date,
            query_to=IN_RUN,
            status="completed",
            result={"m": 1},
        )

        recalculation_id = self._sync(exp)

        assert recalculation_id is not None
        recalc = ExperimentMetricsRecalculation.objects.get(id=recalculation_id)
        assert recalc.metric_uuids == ["sm1"]
        assert [r["metric_uuid"] for r in get_run_results(recalc)] == ["sm1"]

    def test_leaves_metric_types_the_daily_run_cannot_compute_out_of_the_row(self):
        exp = self._experiment("sync-retention", [_mean_metric("m1"), _retention_metric("r1")])
        self._timeseries_point(exp, "m1", IN_RUN, {"m": 1})

        recalculation_id = self._sync(exp)

        assert recalculation_id is not None
        recalc = ExperimentMetricsRecalculation.objects.get(id=recalculation_id)
        assert recalc.total_metrics == 1
        assert recalc.metric_uuids == ["m1"]
        assert {r["metric_uuid"] for r in get_run_results(recalc)} == {"m1"}

    def test_counts_a_supported_metric_without_a_point_as_a_gap(self):
        exp = self._experiment("sync-gap", [_mean_metric("m1"), _mean_metric("m2")])
        self._timeseries_point(exp, "m1", IN_RUN, {"m": 1})

        recalculation_id = self._sync(exp)

        assert recalculation_id is not None
        recalc = ExperimentMetricsRecalculation.objects.get(id=recalculation_id)
        assert recalc.total_metrics == 2
        assert recalc.metric_uuids == ["m1", "m2"]
        assert {r["metric_uuid"] for r in get_run_results(recalc)} == {"m1"}

    @parameterized.expand(
        [
            ("point_before_this_run", BEFORE_RUN, None),
            ("point_in_the_future", IN_FUTURE, None),
            ("recalculation_already_newer", IN_RUN, LATER_IN_RUN),
        ]
    )
    def test_skips_when_no_point_qualifies_or_a_newer_run_exists(
        self, _name: str, point_query_to: datetime, existing_recalc_query_to: datetime | None
    ):
        exp = self._experiment(f"sync-skip-{_name}", [_mean_metric("m1")])
        self._timeseries_point(exp, "m1", point_query_to, {"m": 1})
        if existing_recalc_query_to is not None:
            ExperimentMetricsRecalculation.objects.create(
                team=self.team,
                experiment=exp,
                status=ExperimentMetricsRecalculation.Status.COMPLETED,
                query_to=existing_recalc_query_to,
                completed_at=existing_recalc_query_to,
            )
        before = ExperimentMetricsRecalculation.objects.filter(experiment=exp).count()

        assert self._sync(exp) is None
        assert ExperimentMetricsRecalculation.objects.filter(experiment=exp).count() == before

    @parameterized.expand([("inline_workflow_first", False), ("saved_workflow_first", True)])
    def test_two_workflow_passes_fill_one_row_for_the_day(self, _name: str, saved_first: bool):
        exp = self._experiment(f"sync-two-{_name}", [_mean_metric("m1")])
        self._link_saved_metric(exp, "s1")
        inline_started, inline_point, inline_done = RUN_STARTED_AT, IN_RUN, IN_RUN + timedelta(seconds=30)
        saved_started = IN_RUN + timedelta(minutes=1)
        saved_point, saved_done = saved_started + timedelta(minutes=2), saved_started + timedelta(minutes=3)
        self._timeseries_point(exp, "m1", inline_point, {"m": 1})
        self._timeseries_point(exp, "s1", saved_point, {"s": 1})
        passes = [(inline_started, inline_done), (saved_started, saved_done)]
        if saved_first:
            passes.reverse()

        for run_started_at, now in passes:
            self._sync(exp, now=now, run_started_at=run_started_at)

        rows = ExperimentMetricsRecalculation.objects.filter(experiment=exp)
        assert rows.count() == 1
        recalc = rows.get()
        assert recalc.total_metrics == 2
        results = {r["metric_uuid"]: r["result"] for r in get_run_results(recalc)}
        assert results == {"m1": {"m": 1}, "s1": {"s": 1}}

    @parameterized.expand([("pending",), ("in_progress",)])
    def test_skips_while_a_user_run_is_active_without_a_window(self, status: str):
        exp = self._experiment(f"sync-active-{status}", [_mean_metric("m1")])
        self._timeseries_point(exp, "m1", IN_RUN, {"m": 1})
        ExperimentMetricsRecalculation.objects.create(
            team=self.team,
            experiment=exp,
            status=status,
            started_at=timezone.now() if status == "in_progress" else None,
        )

        assert self._sync(exp) is None
        assert ExperimentMetricsRecalculation.objects.filter(experiment=exp).count() == 1
