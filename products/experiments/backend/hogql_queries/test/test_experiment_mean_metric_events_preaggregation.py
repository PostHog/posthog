from datetime import UTC, datetime
from typing import cast

from posthog.test.base import _create_event, _create_person
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    EventsNode,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentQuery,
    ExperimentQueryResponse,
    IntervalType,
)

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.preaggregation.experiment_metric_events_sql import SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE
from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.experiments.backend.hogql_queries.base_query_utils import experiment_window
from products.experiments.backend.hogql_queries.experiment_query_builder import (
    ExperimentQueryBuilder,
    get_exposure_config_params_for_builder,
)
from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.hogql_queries.exposure_query_logic import get_entity_key
from products.experiments.backend.hogql_queries.metric_events_precompute import MetricEventsPrecompute
from products.experiments.backend.hogql_queries.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentMeanMetricEventsPreaggregation(ExperimentQueryRunnerBaseTest):
    def _build_lazy_computation_builder(
        self, experiment, feature_flag, metric, as_of: datetime | None = None
    ) -> ExperimentQueryBuilder:
        exposure_params = get_exposure_config_params_for_builder(
            experiment.exposure_criteria, experiment.team, experiment.start_date
        )
        as_of = as_of if as_of is not None else datetime.now(UTC)
        date_range = experiment_window(experiment, self.team, as_of)
        return ExperimentQueryBuilder(
            team=self.team,
            feature_flag_key=feature_flag.key,
            exposure_config=exposure_params.exposure_config,
            filter_test_accounts=exposure_params.filter_test_accounts,
            multiple_variant_handling=exposure_params.multiple_variant_handling,
            variants=[v["key"] for v in feature_flag.variants],
            date_range_query=QueryDateRange(
                date_range=date_range,
                team=self.team,
                interval=IntervalType.DAY,
                now=as_of,
            ),
            entity_key=get_entity_key(feature_flag.filters.get("aggregation_group_type_index")),
            metric=metric,
        )

    def _build_runner(self, experiment, metric: ExperimentMeanMetric, as_of: datetime | None = None):
        query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        return ExperimentQueryRunner(query=query, team=self.team, as_of=as_of)

    def _create_exposure_event(self, distinct_id, feature_flag, variant, timestamp):
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id=distinct_id,
            timestamp=timestamp,
            properties={
                f"$feature/{feature_flag.key}": variant,
                "$feature_flag_response": variant,
                "$feature_flag": feature_flag.key,
            },
        )

    def test_precomputed_result_tolerates_replayed_build_rows(self):
        feature_flag = self.create_feature_flag(key="mean-metric-events-replay")
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 10),
        )
        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase", math=ExperimentMetricMathType.SUM, math_property="amount")
        )
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        for variant, count in (("control", 3), ("test", 3)):
            for i in range(count):
                _create_person(distinct_ids=[f"{variant}_{i}"], team_id=self.team.pk)
                self._create_exposure_event(
                    f"{variant}_{i}", feature_flag, variant, datetime(2024, 1, 2, 12, 0, tzinfo=UTC)
                )
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"{variant}_{i}",
                    timestamp=datetime(2024, 1, 3, 12, 0, tzinfo=UTC),
                    properties={"amount": 10 * (i + 1)},
                )

        self._disable_precomputation()
        direct_runner = self._build_runner(experiment, metric)
        direct_result = cast(ExperimentQueryResponse, direct_runner.calculate())

        # First precomputed run builds the jobs whose rows the second run will re-read.
        self._enable_precomputation()
        first_runner = self._build_runner(experiment, metric)
        first_runner.calculate()
        assert first_runner._metric_events_precomputed is True

        # Simulate a replayed build INSERT: every stored metric-event row appears twice
        # under the same job. ReplacingMergeTree only collapses these at merge time, so
        # the read must dedup by event identity or sums double.
        table = SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE()
        rows_before = sync_execute(
            f"SELECT count() FROM {table} WHERE team_id = %(team_id)s", {"team_id": self.team.pk}
        )[0][0]
        assert rows_before > 0
        sync_execute(
            f"INSERT INTO {table} SELECT * FROM {table} WHERE team_id = %(team_id)s",
            {"team_id": self.team.pk},
        )

        precomputed_runner = self._build_runner(experiment, metric)
        precomputed_result = cast(ExperimentQueryResponse, precomputed_runner.calculate())
        assert precomputed_runner._metric_events_precomputed is True

        assert direct_result.baseline is not None
        assert precomputed_result.baseline is not None
        assert precomputed_result.baseline.number_of_samples == direct_result.baseline.number_of_samples
        assert precomputed_result.baseline.sum == direct_result.baseline.sum
        assert direct_result.variant_results is not None
        assert precomputed_result.variant_results is not None
        assert precomputed_result.variant_results[0].sum == direct_result.variant_results[0].sum
        assert (
            precomputed_result.variant_results[0].number_of_samples
            == direct_result.variant_results[0].number_of_samples
        )

    def test_cuped_mean_metric_reads_covariate_from_precomputed_metric_events(self):
        feature_flag = self.create_feature_flag(key="mean-metric-events-cuped")
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2024, 1, 10),
            end_date=datetime(2024, 1, 20),
        )
        experiment.stats_config = {"method": "frequentist", "cuped": {"enabled": True, "lookback_days": 7}}
        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase", math=ExperimentMetricMathType.SUM, math_property="amount")
        )
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        # The purchase before the experiment start is the covariate. Only a build that also
        # covers the lookback window can serve it from the precomputed table.
        for variant in ("control", "test"):
            for i in range(3):
                distinct_id = f"{variant}_{i}"
                _create_person(distinct_ids=[distinct_id], team_id=self.team.pk)
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=distinct_id,
                    timestamp=datetime(2024, 1, 6, 12, 0, tzinfo=UTC),
                    properties={"amount": 5 * (i + 1)},
                )
                self._create_exposure_event(
                    distinct_id, feature_flag, variant, datetime(2024, 1, 11, 12, 0, tzinfo=UTC)
                )
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=distinct_id,
                    timestamp=datetime(2024, 1, 12, 12, 0, tzinfo=UTC),
                    properties={"amount": 10 * (i + 1)},
                )

        self._disable_precomputation()
        direct_result = cast(ExperimentQueryResponse, self._build_runner(experiment, metric).calculate())

        self._enable_precomputation()
        precomputed_runner = self._build_runner(experiment, metric)
        precomputed_result = cast(ExperimentQueryResponse, precomputed_runner.calculate())
        assert precomputed_runner._metric_events_precomputed is True
        assert precomputed_runner.metric_events_path == "precomputed"

        assert direct_result.baseline is not None and direct_result.variant_results is not None
        assert precomputed_result.baseline is not None and precomputed_result.variant_results is not None
        assert direct_result.baseline.covariate_sum == 5 + 10 + 15
        for direct, precomputed in zip(
            [direct_result.baseline, *direct_result.variant_results],
            [precomputed_result.baseline, *precomputed_result.variant_results],
        ):
            assert precomputed.key == direct.key
            assert precomputed.number_of_samples == direct.number_of_samples
            assert precomputed.sum == direct.sum
            assert precomputed.covariate_sum == direct.covariate_sum
            assert precomputed.covariate_sum_squares == direct.covariate_sum_squares
            assert precomputed.covariate_sum_product == direct.covariate_sum_product

    @parameterized.expand([("flag_on", True, None), ("flag_off", False, "cuped")])
    def test_cuped_metric_events_precompute_gate(self, _name, flag_enabled, skip_reason):
        feature_flag = self.create_feature_flag(key="mean-metric-events-cuped-gate")
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 10),
        )
        experiment.stats_config = {"method": "frequentist", "cuped": {"enabled": True}}
        experiment.save()
        runner = self._build_runner(experiment, ExperimentMeanMetric(source=EventsNode(event="purchase")))

        with patch.object(MetricEventsPrecompute, "cuped_flag_enabled", return_value=flag_enabled):
            assert runner._metric_events_ineligibility_reason() == skip_reason
            assert runner._metric_events_precompute_applicable() is (skip_reason is None)

    @patch("products.experiments.backend.hogql_queries.metric_events_precompute.ensure_precomputed")
    def test_cuped_build_counts_lookback_in_calendar_days_of_project_timezone(self, mock_ensure_precomputed):
        self.team.timezone = "America/New_York"
        self.team.save()
        feature_flag = self.create_feature_flag(key="mean-metric-events-cuped-dst")
        # The experiment starts the day after the 2024 fall-back, so seven calendar days earlier in
        # New York is 169 hours earlier in UTC. The write query subtracts calendar days too, and a
        # build that started an hour later would never store the first hour the read asks for.
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2024, 11, 4, 0, 30),
            end_date=datetime(2024, 11, 20),
        )
        experiment.stats_config = {"method": "frequentist", "cuped": {"enabled": True, "lookback_days": 7}}
        experiment.save()
        metric = ExperimentMeanMetric(source=EventsNode(event="purchase"))

        runner = self._build_runner(experiment, metric)
        runner._ensure_metric_events_precomputed(runner._query_builder())

        assert mock_ensure_precomputed.call_args.kwargs["time_range_start"] == datetime(
            2024, 10, 27, 23, 30, tzinfo=UTC
        )

    @patch("products.analytics_platform.backend.lazy_computation.lazy_computation_executor.sync_execute")
    def test_mean_metric_events_precomputation_hash_ignores_moving_experiment_end(self, mock_sync_execute):
        feature_flag = self.create_feature_flag(key="stable-mean-metric-events-hash")
        # Running experiment (no end_date) so the window end follows as_of. The mean build
        # query must keep the experiment date bounds as sentinel placeholders — resolving
        # them into the query (e.g. via _build_metric_predicate) would change the job hash
        # on every load and silently defeat cache reuse.
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2024, 1, 1),
            end_date=None,
        )
        experiment.end_date = None
        experiment.save(update_fields=["end_date"])
        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase", math=ExperimentMetricMathType.SUM, math_property="amount")
        )

        first_as_of = datetime(2024, 1, 5, 12, 0, tzinfo=UTC)
        second_as_of = datetime(2024, 1, 5, 12, 30, tzinfo=UTC)

        first_result = self._build_runner(experiment, metric, as_of=first_as_of)._ensure_metric_events_precomputed(
            self._build_lazy_computation_builder(experiment, feature_flag, metric, as_of=first_as_of)
        )
        second_result = self._build_runner(experiment, metric, as_of=second_as_of)._ensure_metric_events_precomputed(
            self._build_lazy_computation_builder(experiment, feature_flag, metric, as_of=second_as_of)
        )

        assert first_result.ready is True
        assert second_result.ready is True
        # The stable hash shares the complete day-aligned jobs across as_of values;
        # only the final partial day, claimed up to each as_of, is rebuilt.
        first_jobs = set(first_result.job_ids)
        second_jobs = set(second_result.job_ids)
        assert len(second_jobs) == len(first_jobs)
        assert len(first_jobs & second_jobs) == len(first_jobs) - 1
        assert mock_sync_execute.call_count == len(first_jobs) + 1

    @patch("products.analytics_platform.backend.lazy_computation.lazy_computation_executor.sync_execute")
    def test_dau_metric_shares_precompute_jobs_with_count_metric(self, mock_sync_execute):
        feature_flag = self.create_feature_flag(key="shared-mean-metric-events-jobs")
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 10),
        )
        # ID-valued math stores the same rows as a count metric, so the build
        # queries must hash the same and share jobs instead of building twice.
        count_metric = ExperimentMeanMetric(source=EventsNode(event="purchase"))
        dau_metric = ExperimentMeanMetric(source=EventsNode(event="purchase", math=ExperimentMetricMathType.DAU))

        count_result = self._build_runner(experiment, count_metric)._ensure_metric_events_precomputed(
            self._build_lazy_computation_builder(experiment, feature_flag, count_metric)
        )
        dau_result = self._build_runner(experiment, dau_metric)._ensure_metric_events_precomputed(
            self._build_lazy_computation_builder(experiment, feature_flag, dau_metric)
        )

        assert count_result.ready is True
        assert dau_result.ready is True
        assert count_result.job_ids == dau_result.job_ids
        # Only the count run executed INSERTs; the dau run reused its jobs.
        assert mock_sync_execute.call_count == len(count_result.job_ids)

    @parameterized.expand(
        [
            ("count_default_math", EventsNode(event="purchase"), None),
            (
                "sum",
                EventsNode(event="purchase", math=ExperimentMetricMathType.SUM, math_property="amount"),
                None,
            ),
            (
                "avg",
                EventsNode(event="purchase", math=ExperimentMetricMathType.AVG, math_property="amount"),
                None,
            ),
            (
                "min",
                EventsNode(event="purchase", math=ExperimentMetricMathType.MIN, math_property="amount"),
                None,
            ),
            (
                "max",
                EventsNode(event="purchase", math=ExperimentMetricMathType.MAX, math_property="amount"),
                None,
            ),
            (
                "unique_session",
                EventsNode(event="purchase", math=ExperimentMetricMathType.UNIQUE_SESSION),
                None,
            ),
            (
                "dau",
                EventsNode(event="purchase", math=ExperimentMetricMathType.DAU),
                None,
            ),
            (
                "unique_group",
                EventsNode(event="purchase", math=ExperimentMetricMathType.UNIQUE_GROUP, math_group_type_index=1),
                "unsupported_math",
            ),
            (
                "hogql_user_expression",
                EventsNode(event="purchase", math=ExperimentMetricMathType.HOGQL, math_hogql="sum(properties.amount)"),
                "unsupported_math",
            ),
            (
                "session_property",
                EventsNode(event="purchase", math=ExperimentMetricMathType.SUM, math_property="$session_duration"),
                "session_property_math",
            ),
        ]
    )
    def test_mean_metric_events_precompute_gate(self, _name, source, skip_reason):
        feature_flag = self.create_feature_flag(key="mean-metric-events-gate")
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 10),
        )
        metric = ExperimentMeanMetric(source=source)

        runner = self._build_runner(experiment, metric)

        assert runner._metric_events_ineligibility_reason() == skip_reason
        assert runner._metric_events_precompute_applicable() is (skip_reason is None)
