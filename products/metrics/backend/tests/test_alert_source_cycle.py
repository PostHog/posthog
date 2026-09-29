from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.models.scoping import team_scope

from products.alerts.backend.facade.contracts import SourceBatchEvaluation
from products.alerts.backend.facade.platform_alerts import record_outcomes
from products.alerts.backend.models import AlertConfiguration, PlatformAlert, PlatformAlertConfiguration
from products.metrics.backend.alert_checkpoint import CHECKPOINT_MAX_STALENESS
from products.metrics.backend.alert_source_cycle import (
    BATCH_QUERY_BUDGET_SECONDS,
    MAX_QUERY_SECONDS,
    evaluate_metrics_batch,
)
from products.metrics.backend.facade.contracts import MetricPoint, MetricSeries

_MODULE = "products.metrics.backend.alert_source_cycle"


def _series(values_newest_first: list[float | None], *, end: datetime, step: timedelta, labels=None) -> MetricSeries:
    points = []
    for index, value in enumerate(reversed(values_newest_first)):
        bucket_start = end - step * (len(values_newest_first) - index)
        points.append(MetricPoint(time=bucket_start.isoformat(), value=value))
    return MetricSeries(labels=labels or {}, points=tuple(points), metric_name="m1", clause="a")


class TestMetricsAlertEvaluation(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.cutoff = datetime(2026, 9, 29, 10, tzinfo=UTC)
        self.due_at = self.cutoff - timedelta(minutes=1)

    def _configuration(self, **overrides) -> PlatformAlertConfiguration:
        defaults = {
            "team": self.team,
            "name": "API p95 latency",
            "source_kind": PlatformAlertConfiguration.SourceKind.METRICS,
            "source_config": {
                "type": "MetricsAlertSource",
                "clauses": [{"name": "a", "metric_name": "m1", "aggregation": "sum"}],
            },
            "threshold_count": 10,
            "threshold_operator": "above",
            "window_minutes": 5,
            "check_interval_minutes": 5,
            "next_check_at": self.due_at,
        }
        defaults.update(overrides)
        with team_scope(self.team.id):
            return PlatformAlertConfiguration.objects.create(**defaults)

    def _run(
        self,
        *configurations: PlatformAlertConfiguration,
        series: list[MetricSeries] | None = None,
        checkpoint: datetime | None = None,
        query_error: Exception | None = None,
    ):
        if series is None:
            series = [_series([500.0], end=self.due_at, step=timedelta(minutes=5))]
        with (
            patch(f"{_MODULE}.fetch_live_metrics_checkpoint", return_value=checkpoint),
            patch(f"{_MODULE}.run_metric_query") as query,
        ):
            if query_error is not None:
                query.side_effect = query_error
            else:
                query.return_value = series
            slot = (configurations[0].next_check_at or self.cutoff).replace(second=0, microsecond=0).isoformat()
            return evaluate_metrics_batch(self.team.id, slot, self.cutoff), query

    def _record(self, evaluation: SourceBatchEvaluation) -> None:
        record_outcomes(self.team.id, evaluation.outcomes, self.cutoff)

    def _alert(self, configuration: PlatformAlertConfiguration) -> PlatformAlert:
        with team_scope(self.team.id):
            return PlatformAlert.objects.get(configuration=configuration, grouping_key="")

    def test_a_breaching_series_fires_and_records_its_own_state(self) -> None:
        configuration = self._configuration()

        evaluation, _ = self._run(configuration)
        self._record(evaluation)

        assert [t.notification for preview in evaluation.previews for t in preview.transitions] == ["fire"]
        alert = self._alert(configuration)
        with team_scope(self.team.id):
            configuration.refresh_from_db()
        assert alert.state == PlatformAlert.State.FIRING
        assert alert.last_notified_at is not None
        assert configuration.next_check_at is not None
        assert configuration.next_check_at > self.cutoff

    def test_a_series_under_the_threshold_does_not_fire(self) -> None:
        configuration = self._configuration()

        evaluation, _ = self._run(configuration, series=[_series([3.0], end=self.due_at, step=timedelta(minutes=5))])

        assert evaluation.previews == ()
        assert evaluation.outcomes[0].new_state == "not_firing"

    def test_the_evaluation_key_comes_from_the_due_slot_not_the_clock(self) -> None:
        configuration = self._configuration()

        evaluation, query = self._run(configuration)

        assert evaluation.previews[0].evaluation_key == f"{configuration.id}:window:{self.due_at.isoformat()}"
        assert query.call_args.kwargs["request"].date_to == self.due_at

    def test_the_window_is_anchored_on_the_due_slot_with_an_explicit_interval(self) -> None:
        configuration = self._configuration(window_minutes=15, evaluation_periods=3)

        _, query = self._run(
            configuration, series=[_series([50.0, 50.0, 50.0], end=self.due_at, step=timedelta(minutes=15))]
        )

        request = query.call_args.kwargs["request"]
        assert request.interval == "minute_15"
        assert request.date_from == self.due_at - timedelta(minutes=45)
        assert request.date_to == self.due_at

    def test_a_fresh_checkpoint_clamps_the_window_end(self) -> None:
        configuration = self._configuration()
        checkpoint = self.due_at - timedelta(seconds=30)

        evaluation, query = self._run(configuration, checkpoint=checkpoint)

        assert query.call_args.kwargs["request"].date_to == checkpoint
        assert evaluation.previews[0].evaluation_key == f"{configuration.id}:window:{checkpoint.isoformat()}"

    def test_a_stale_checkpoint_is_ignored(self) -> None:
        configuration = self._configuration()
        checkpoint = self.due_at - CHECKPOINT_MAX_STALENESS - timedelta(seconds=1)

        _, query = self._run(configuration, checkpoint=checkpoint)

        assert query.call_args.kwargs["request"].date_to == self.due_at

    def test_a_null_current_point_is_inconclusive_and_keeps_a_firing_alert_firing(self) -> None:
        configuration = self._configuration()
        with team_scope(self.team.id):
            PlatformAlert.objects.create(
                team=self.team, configuration=configuration, grouping_key="", state=PlatformAlert.State.FIRING
            )

        evaluation, _ = self._run(
            configuration, series=[_series([None, 500.0], end=self.due_at, step=timedelta(minutes=5))]
        )
        self._record(evaluation)

        assert evaluation.previews == ()
        assert evaluation.outcomes[0].new_state == "firing"
        assert evaluation.outcomes[0].consecutive_failures == 0

    def test_no_points_is_inconclusive_for_any_operator(self) -> None:
        for operator in ("above", "below"):
            configuration = self._configuration(threshold_operator=operator, next_check_at=self.due_at)
            empty = MetricSeries(labels={}, points=(), metric_name="m1", clause="a")

            evaluation, _ = self._run(configuration, series=[empty])

            assert evaluation.previews == (), operator
            assert evaluation.outcomes[0].new_state == "not_firing", operator

    def test_an_unsupported_window_is_a_broken_config(self) -> None:
        configuration = self._configuration(window_minutes=7)

        evaluation, query = self._run(configuration)

        assert evaluation.outcomes[0].new_state == "broken"
        assert evaluation.previews == ()
        query.assert_not_called()

    def test_an_invalid_source_config_is_a_broken_config(self) -> None:
        configuration = self._configuration(source_config={"type": "MetricsAlertSource", "clauses": []})

        evaluation, query = self._run(configuration)

        assert evaluation.outcomes[0].new_state == "broken"
        query.assert_not_called()

    def test_a_grouped_result_is_a_failed_check_until_grouping_lands(self) -> None:
        configuration = self._configuration()
        grouped = [
            _series([500.0], end=self.due_at, step=timedelta(minutes=5), labels={"service_name": "api"}),
            _series([1.0], end=self.due_at, step=timedelta(minutes=5), labels={"service_name": "web"}),
        ]

        evaluation, _ = self._run(configuration, series=grouped)

        assert evaluation.outcomes[0].consecutive_failures == 1
        assert evaluation.outcomes[0].new_state != "firing"

    def test_a_query_the_user_can_fix_counts_toward_broken_and_advances_the_schedule(self) -> None:
        configuration = self._configuration()

        evaluation, _ = self._run(configuration, query_error=ValueError("date range too wide"))
        self._record(evaluation)

        assert evaluation.outcomes[0].consecutive_failures == 1
        with team_scope(self.team.id):
            configuration.refresh_from_db()
        assert configuration.next_check_at is not None
        assert configuration.next_check_at > self.cutoff

    def test_an_unknown_query_error_is_transient_and_holds_the_failure_counter(self) -> None:
        configuration = self._configuration()

        evaluation, _ = self._run(configuration, query_error=Exception("boom"))
        self._record(evaluation)

        assert evaluation.outcomes[0].consecutive_failures == 0
        with team_scope(self.team.id):
            configuration.refresh_from_db()
        assert configuration.next_check_at is not None
        assert configuration.next_check_at > self.cutoff

    def test_the_query_is_capped_below_the_batch_budget(self) -> None:
        configuration = self._configuration()

        _, query = self._run(configuration)

        query_settings = query.call_args.kwargs["query_settings"]
        assert query_settings is not None
        assert 0 < query_settings.max_execution_time <= MAX_QUERY_SECONDS
        assert query_settings.timeout_overflow_mode == "throw"
        assert MAX_QUERY_SECONDS < BATCH_QUERY_BUDGET_SECONDS

    def test_the_insight_alert_rows_are_never_written(self) -> None:
        configuration = self._configuration()

        evaluation, _ = self._run(configuration)
        self._record(evaluation)

        with team_scope(self.team.id):
            assert AlertConfiguration.objects.filter(team=self.team).count() == 0
