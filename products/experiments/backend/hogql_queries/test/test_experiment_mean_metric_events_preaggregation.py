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
        assert first_result.job_ids == second_result.job_ids
        assert mock_sync_execute.call_count == len(first_result.job_ids)

    @parameterized.expand(
        [
            ("count_default_math", EventsNode(event="purchase"), True),
            (
                "sum",
                EventsNode(event="purchase", math=ExperimentMetricMathType.SUM, math_property="amount"),
                True,
            ),
            (
                "avg_not_yet_allowlisted",
                EventsNode(event="purchase", math=ExperimentMetricMathType.AVG, math_property="amount"),
                False,
            ),
            (
                "unique_session_id_valued",
                EventsNode(event="purchase", math=ExperimentMetricMathType.UNIQUE_SESSION),
                False,
            ),
            (
                "hogql_user_expression",
                EventsNode(event="purchase", math=ExperimentMetricMathType.HOGQL, math_hogql="sum(properties.amount)"),
                False,
            ),
            (
                "session_property",
                EventsNode(event="purchase", math=ExperimentMetricMathType.SUM, math_property="$session_duration"),
                False,
            ),
        ]
    )
    def test_mean_metric_events_precompute_gate(self, _name, source, applicable):
        feature_flag = self.create_feature_flag(key="mean-metric-events-gate")
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 10),
        )
        metric = ExperimentMeanMetric(source=source)

        runner = self._build_runner(experiment, metric)

        assert runner._metric_events_precompute_applicable() is applicable
