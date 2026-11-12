from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest

from parameterized import parameterized

from products.experiments.backend.metric_calculation.config import get_metric_calculation_config
from products.experiments.backend.metric_calculation.results import _recalc_fingerprint
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentMetricsRecalculation,
)
from products.experiments.backend.staff_operations import format_duration, get_recalculation
from products.feature_flags.backend.models.feature_flag import FeatureFlag


def _mean_metric(uuid: str, name: str | None = None) -> dict:
    metric: dict = {
        "uuid": uuid,
        "kind": "ExperimentMetric",
        "metric_type": "mean",
        "source": {"kind": "EventsNode", "event": "purchase"},
    }
    if name is not None:
        metric["name"] = name
    return metric


_BASE = datetime(2026, 1, 1, tzinfo=UTC)


class TestFormatDuration:
    @parameterized.expand(
        [
            ("sub_minute", 45, "45s"),
            ("minutes_and_seconds", 250, "4m 10s"),
            ("exact_minute_drops_seconds", 120, "2m"),
            ("zero_reads_as_seconds", 0, "0s"),
            ("hours", 3661, "1h 1m 1s"),
        ]
    )
    def test_formats_elapsed(self, _name: str, elapsed_seconds: int, expected: str) -> None:
        assert format_duration(_BASE, _BASE + timedelta(seconds=elapsed_seconds)) == expected

    @parameterized.expand([("missing_start", None, _BASE), ("missing_end", _BASE, None)])
    def test_missing_bound_is_none(self, _name: str, started: datetime | None, completed: datetime | None) -> None:
        assert format_duration(started, completed) is None

    def test_negative_duration_is_none(self) -> None:
        assert format_duration(_BASE + timedelta(seconds=10), _BASE) is None


class TestStaffRecalculation(BaseTest):
    def _launched_experiment(self) -> Experiment:
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="admin-panel-flag",
            name="Flag",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        exp = Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            feature_flag=flag,
            name="exp",
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
        )
        exp.metrics = [_mean_metric("m-named", name="Signups"), _mean_metric("m-discovery")]
        exp.save()
        return exp

    def test_failures_prefer_metric_errors_and_include_discovery_only(self) -> None:
        exp = self._launched_experiment()
        recalc = ExperimentMetricsRecalculation.objects.create(
            team=self.team,
            experiment=exp,
            status=ExperimentMetricsRecalculation.Status.FAILED,
            total_metrics=2,
            metric_uuids=["m-named", "m-discovery"],
            # m-discovery failed in discovery (no result row); m-named has a metric_errors entry that must
            # win over any result-row message.
            metric_errors={
                "m-named": {"message": "row-level query failed"},
                "m-discovery": {"message": "metric could not be resolved"},
            },
            started_at=datetime(2026, 1, 2, 10, 0, 0, tzinfo=UTC),
            completed_at=datetime(2026, 1, 2, 10, 4, 10, tzinfo=UTC),
        )

        run = get_recalculation(str(recalc.pk))

        assert run is not None
        assert run.duration == "4m 10s"
        by_uuid = {f.metric_uuid: f for f in run.failures}
        # metric_errors message wins, and a named metric shows its name not its uuid.
        assert by_uuid["m-named"].error == "row-level query failed"
        assert by_uuid["m-named"].metric_name == "Signups"
        # a discovery-only failure with no result row is still surfaced.
        assert by_uuid["m-discovery"].error == "metric could not be resolved"

    def test_failure_falls_back_to_result_row_message(self) -> None:
        exp = self._launched_experiment()
        query_to = datetime(2026, 1, 2, 10, 0, 0, tzinfo=UTC)
        recalc = ExperimentMetricsRecalculation.objects.create(
            team=self.team,
            experiment=exp,
            status=ExperimentMetricsRecalculation.Status.FAILED,
            total_metrics=2,
            metric_uuids=["m-named"],
            metric_errors={},
            query_to=query_to,
            started_at=datetime(2026, 1, 2, 10, 0, 0, tzinfo=UTC),
            completed_at=datetime(2026, 1, 2, 10, 0, 30, tzinfo=UTC),
        )
        # No metric_errors entry, so the failure text comes from the FAILED result row's error_message.
        calculation_config = get_metric_calculation_config(exp, "m-named")
        assert calculation_config is not None
        ExperimentMetricResult.objects.create(
            experiment=exp,
            metric_uuid="m-named",
            fingerprint=_recalc_fingerprint(calculation_config.calculation_key()),
            query_from=datetime(2026, 1, 1, tzinfo=UTC),
            query_to=query_to,
            status=ExperimentMetricResult.Status.FAILED,
            error_message="timeout in ClickHouse",
        )

        run = get_recalculation(str(recalc.pk))

        assert run is not None
        by_uuid = {f.metric_uuid: f for f in run.failures}
        assert by_uuid["m-named"].error == "timeout in ClickHouse"
