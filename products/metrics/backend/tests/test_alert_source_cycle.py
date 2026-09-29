from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.models.scoping import team_scope

from products.alerts.backend.facade.conditions import compile_condition_bytecode
from products.alerts.backend.facade.contracts import (
    MAX_GROUPS_PER_CONFIGURATION,
    SourceBatchEvaluation,
    grouping_key_for,
)
from products.alerts.backend.facade.platform_alerts import record_outcomes
from products.alerts.backend.models import AlertConfiguration, PlatformAlert, PlatformAlertConfiguration
from products.metrics.backend.alert_checkpoint import CHECKPOINT_MAX_STALENESS
from products.metrics.backend.alert_source_cycle import (
    BATCH_QUERY_BUDGET_SECONDS,
    MAX_QUERY_SECONDS,
    evaluate_metrics_batch,
)
from products.metrics.backend.facade.api import MAX_SERIES_PER_CLAUSE
from products.metrics.backend.facade.contracts import MetricPoint, MetricSeries

_MODULE = "products.metrics.backend.alert_source_cycle"


def _series(values_newest_first: list[float | None], *, end: datetime, step: timedelta, labels=None) -> MetricSeries:
    points = []
    for index, value in enumerate(reversed(values_newest_first)):
        bucket_start = end - step * (len(values_newest_first) - index)
        points.append(MetricPoint(time=bucket_start.isoformat(), value=value))
    return MetricSeries(labels=labels or {}, points=tuple(points), metric_name="m1", clause="a")


class MetricsAlertEvaluationTestCase(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.cutoff = datetime(2026, 9, 29, 10, tzinfo=UTC)
        # Aligned to the five-minute bucket grid the default configuration evaluates on.
        self.due_at = self.cutoff - timedelta(minutes=5)

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


class TestMetricsAlertEvaluation(MetricsAlertEvaluationTestCase):
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
        due_at = self.cutoff - timedelta(minutes=15)
        configuration = self._configuration(window_minutes=15, evaluation_periods=3, next_check_at=due_at)

        _, query = self._run(
            configuration, series=[_series([50.0, 50.0, 50.0], end=due_at, step=timedelta(minutes=15))]
        )

        request = query.call_args.kwargs["request"]
        assert request.interval == "minute_15"
        assert request.date_from == due_at - timedelta(minutes=45)
        assert request.date_to == due_at

    def test_a_fresh_checkpoint_clamps_the_window_end_to_a_complete_bucket(self) -> None:
        configuration = self._configuration()
        checkpoint = self.due_at - timedelta(seconds=30)
        complete = self.due_at - timedelta(minutes=5)

        evaluation, query = self._run(
            configuration, checkpoint=checkpoint, series=[_series([500.0], end=complete, step=timedelta(minutes=5))]
        )

        assert query.call_args.kwargs["request"].date_to == complete
        assert evaluation.previews[0].evaluation_key == f"{configuration.id}:window:{complete.isoformat()}"

    def test_a_due_time_inside_a_bucket_evaluates_the_last_complete_bucket(self) -> None:
        configuration = self._configuration(next_check_at=self.due_at + timedelta(seconds=30))

        _, query = self._run(configuration)

        assert query.call_args.kwargs["request"].date_to == self.due_at

    def test_a_missing_current_bucket_is_not_read_from_an_older_point(self) -> None:
        configuration = self._configuration()
        with team_scope(self.team.id):
            PlatformAlert.objects.create(
                team=self.team, configuration=configuration, grouping_key="", state=PlatformAlert.State.FIRING
            )
        stale = [_series([500.0], end=self.due_at - timedelta(minutes=5), step=timedelta(minutes=5))]

        evaluation, _ = self._run(configuration, series=stale)

        assert evaluation.previews == ()
        assert evaluation.outcomes[0].new_state == "firing"

    def test_the_query_cap_is_split_across_the_clauses(self) -> None:
        configuration = self._configuration(
            source_config={
                "type": "MetricsAlertSource",
                "clauses": [
                    {"name": "errors", "metric_name": "e", "aggregation": "sum"},
                    {"name": "requests", "metric_name": "r", "aggregation": "sum"},
                ],
                "formula": "errors / requests",
            }
        )

        _, query = self._run(
            configuration,
            series=[
                MetricSeries(
                    labels={},
                    points=(MetricPoint(time=(self.due_at - timedelta(minutes=5)).isoformat(), value=0.5),),
                    metric_name=None,
                    clause="formula",
                )
            ],
        )

        assert query.call_args.kwargs["query_settings"].max_execution_time <= MAX_QUERY_SECONDS // 2

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

    def _grouped(self, api: float | None, web: float | None) -> list[MetricSeries]:
        return [
            _series([api], end=self.due_at, step=timedelta(minutes=5), labels={"service_name": "api"}),
            _series([web], end=self.due_at, step=timedelta(minutes=5), labels={"service_name": "web"}),
        ]

    def test_each_label_set_fires_on_its_own(self) -> None:
        configuration = self._configuration()

        evaluation, _ = self._run(configuration, series=self._grouped(api=500.0, web=1.0))
        self._record(evaluation)

        (preview,) = evaluation.previews
        assert [(t.labels, t.notification) for t in preview.transitions] == [({"service_name": "api"}, "fire")]
        with team_scope(self.team.id):
            states = {a.grouping_key: a.state for a in PlatformAlert.objects.filter(configuration=configuration)}
        assert states == {
            grouping_key_for({"service_name": "api"}): "firing",
            grouping_key_for({"service_name": "web"}): "not_firing",
        }

    def test_a_recovering_service_resolves_while_another_keeps_firing(self) -> None:
        configuration = self._configuration()
        first, _ = self._run(configuration, series=self._grouped(api=500.0, web=500.0))
        self._record(first)
        with team_scope(self.team.id):
            configuration.next_check_at = self.due_at
            configuration.save(update_fields=["next_check_at"])

        second, _ = self._run(configuration, series=self._grouped(api=500.0, web=1.0))

        (preview,) = second.previews
        assert [(t.labels, t.notification) for t in preview.transitions] == [({"service_name": "web"}, "resolve")]
        by_key = {o.grouping_key: o.new_state for o in second.outcomes}
        assert by_key[grouping_key_for({"service_name": "api"})] == "firing"
        assert by_key[grouping_key_for({"service_name": "web"})] == "not_firing"

    def test_a_configuration_snooze_mutes_every_group(self) -> None:
        configuration = self._configuration()
        with team_scope(self.team.id):
            PlatformAlert.objects.create(
                team=self.team,
                configuration=configuration,
                grouping_key="",
                snooze_until=self.cutoff + timedelta(hours=1),
            )

        evaluation, _ = self._run(configuration, series=self._grouped(api=500.0, web=500.0))

        assert evaluation.previews == ()
        assert {o.grouping_key: o.new_state for o in evaluation.outcomes if o.grouping_key} == {
            grouping_key_for({"service_name": "api"}): "firing",
            grouping_key_for({"service_name": "web"}): "firing",
        }

    def test_a_vanished_group_does_not_keep_an_old_failure_count_after_a_successful_check(self) -> None:
        configuration = self._configuration(consecutive_failures=2)
        first, _ = self._run(configuration, series=self._grouped(api=500.0, web=500.0))
        self._record(first)
        with team_scope(self.team.id):
            configuration.next_check_at = self.due_at
            configuration.consecutive_failures = 2
            configuration.save(update_fields=["next_check_at", "consecutive_failures"])

        second, _ = self._run(configuration, series=self._grouped(api=500.0, web=None)[:1])
        self._record(second)

        assert {o.consecutive_failures for o in second.outcomes} == {0}
        with team_scope(self.team.id):
            configuration.refresh_from_db()
        assert configuration.consecutive_failures == 0

    def test_the_group_cap_counts_remembered_label_sets_too(self) -> None:
        configuration = self._configuration()
        with team_scope(self.team.id):
            for index in range(MAX_GROUPS_PER_CONFIGURATION):
                PlatformAlert.objects.create(
                    team=self.team,
                    configuration=configuration,
                    grouping_key=grouping_key_for({"pod": f"old-{index:04d}"}),
                    state=PlatformAlert.State.FIRING,
                )
        fresh = [
            _series([500.0], end=self.due_at, step=timedelta(minutes=5), labels={"pod": f"new-{i:04d}"})
            for i in range(2)
        ]

        evaluation, _ = self._run(configuration, series=fresh)
        self._record(evaluation)

        by_key = {o.grouping_key: o for o in evaluation.outcomes}
        assert by_key[""].consecutive_failures == 1
        assert grouping_key_for({"pod": "new-0000"}) not in by_key
        with team_scope(self.team.id):
            assert (
                PlatformAlert.objects.filter(configuration=configuration).exclude(grouping_key="").count()
                == MAX_GROUPS_PER_CONFIGURATION
            )

    def test_a_vanished_group_that_is_not_firing_is_retired_and_frees_its_slot(self) -> None:
        configuration = self._configuration()
        first, _ = self._run(configuration, series=self._grouped(api=1.0, web=500.0))
        self._record(first)
        with team_scope(self.team.id):
            configuration.next_check_at = self.due_at
            configuration.save(update_fields=["next_check_at"])
        replacement = [_series([500.0], end=self.due_at, step=timedelta(minutes=5), labels={"service_name": "worker"})]

        second, _ = self._run(configuration, series=replacement)
        self._record(second)

        with team_scope(self.team.id):
            keys = set(PlatformAlert.objects.filter(configuration=configuration).values_list("grouping_key", flat=True))
        # api resolved before it vanished, so its row is gone; web was firing when it vanished, so it stays.
        assert grouping_key_for({"service_name": "api"}) not in keys
        assert grouping_key_for({"service_name": "web"}) in keys
        assert grouping_key_for({"service_name": "worker"}) in keys

    def test_stale_not_firing_groups_do_not_consume_the_cap(self) -> None:
        configuration = self._configuration()
        with team_scope(self.team.id):
            for index in range(MAX_GROUPS_PER_CONFIGURATION):
                PlatformAlert.objects.create(
                    team=self.team,
                    configuration=configuration,
                    grouping_key=grouping_key_for({"pod": f"old-{index:04d}"}),
                )
        fresh = [_series([500.0], end=self.due_at, step=timedelta(minutes=5), labels={"pod": "new-0000"})]

        evaluation, _ = self._run(configuration, series=fresh)

        by_key = {o.grouping_key: o for o in evaluation.outcomes}
        assert by_key[grouping_key_for({"pod": "new-0000"})].new_state == "firing"
        assert "" not in by_key or by_key[""].consecutive_failures == 0

        # The facade truncates each clause at MAX_SERIES_PER_CLAUSE, so a cap at or above it could never see overflow.
        assert MAX_GROUPS_PER_CONFIGURATION < MAX_SERIES_PER_CLAUSE

    def test_group_overflow_is_recorded_as_an_error_on_the_root_group(self) -> None:
        configuration = self._configuration()
        many = [
            _series([500.0], end=self.due_at, step=timedelta(minutes=5), labels={"pod": f"pod-{i:04d}"})
            for i in range(MAX_GROUPS_PER_CONFIGURATION + 1)
        ]

        evaluation, _ = self._run(configuration, series=many)

        by_key = {o.grouping_key: o for o in evaluation.outcomes}
        assert by_key[""].consecutive_failures == 1
        assert len(by_key) == MAX_GROUPS_PER_CONFIGURATION + 1

    def test_a_vanished_series_is_inconclusive_for_its_group(self) -> None:
        configuration = self._configuration()
        first, _ = self._run(configuration, series=self._grouped(api=500.0, web=500.0))
        self._record(first)
        with team_scope(self.team.id):
            configuration.next_check_at = self.due_at
            configuration.save(update_fields=["next_check_at"])

        second, _ = self._run(configuration, series=self._grouped(api=500.0, web=None)[:1])

        by_key = {o.grouping_key: o for o in second.outcomes}
        web = by_key[grouping_key_for({"service_name": "web"})]
        assert web.new_state == "firing"
        assert second.previews == ()

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


class TestMetricsHogConditions(MetricsAlertEvaluationTestCase):
    def _hog(self, source: str, **overrides) -> PlatformAlertConfiguration:
        return self._configuration(
            condition_type="hog", condition_bytecode=compile_condition_bytecode(source), **overrides
        )

    def test_a_hog_condition_decides_the_breach_instead_of_the_threshold(self) -> None:
        # 500 is above the threshold of 10, and the condition still says no.
        configuration = self._hog("return value > 1000")

        evaluation, _ = self._run(configuration)

        assert evaluation.previews == ()
        assert evaluation.outcomes[0].new_state == "not_firing"

    def test_a_hog_condition_sees_every_evaluated_window(self) -> None:
        configuration = self._hog("return values[1] > values[2] and window.count == 3", evaluation_periods=3)

        evaluation, _ = self._run(
            configuration, series=[_series([30.0, 20.0, 10.0], end=self.due_at, step=timedelta(minutes=5))]
        )

        assert [t.notification for p in evaluation.previews for t in p.transitions] == ["fire"]

    def test_a_failing_hog_condition_records_a_failed_outcome_and_leaves_other_alerts_untouched(self) -> None:
        looping = self._hog("while (true) {}")
        healthy = self._configuration()

        evaluation, _ = self._run(looping, healthy)

        by_id = {o.configuration_id: o for o in evaluation.outcomes}
        assert by_id[looping.id].consecutive_failures == 1
        assert by_id[healthy.id].new_state == "firing"
        announced = {p.alert_id: [t.notification for t in p.transitions] for p in evaluation.previews}
        assert announced == {str(looping.id): ["error"], str(healthy.id): ["fire"]}

    def test_an_exhausted_condition_budget_keeps_the_alert_due(self) -> None:
        first = self._hog("return true")
        second = self._hog("return true")

        with patch(f"{_MODULE}.CONDITION_BATCH_BUDGET", timedelta(microseconds=1)):
            evaluation, _ = self._run(first, second)
        self._record(evaluation)

        assert [o.configuration_id for o in evaluation.outcomes] == [first.id]
        with team_scope(self.team.id):
            second.refresh_from_db()
        assert second.next_check_at == self.due_at
