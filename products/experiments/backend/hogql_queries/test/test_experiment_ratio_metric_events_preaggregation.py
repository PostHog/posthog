from datetime import UTC, datetime

from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    EventsNode,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentQuery,
    ExperimentRatioMetric,
    IntervalType,
)

from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.experiments.backend.hogql_queries.base_query_utils import experiment_window
from products.experiments.backend.hogql_queries.experiment_query_builder import (
    ExperimentQueryBuilder,
    get_exposure_config_params_for_builder,
)
from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.hogql_queries.exposure_query_logic import get_entity_key
from products.experiments.backend.hogql_queries.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest

PURCHASE_SUM = EventsNode(event="purchase", math=ExperimentMetricMathType.SUM, math_property="amount")
PURCHASE_COUNT = EventsNode(event="purchase")


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentRatioMetricEventsPreaggregation(ExperimentQueryRunnerBaseTest):
    def _build_lazy_computation_builder(self, experiment, feature_flag, metric) -> ExperimentQueryBuilder:
        exposure_params = get_exposure_config_params_for_builder(
            experiment.exposure_criteria, experiment.team, experiment.start_date
        )
        as_of = datetime.now(UTC)
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

    def _build_runner(self, experiment, metric: ExperimentMeanMetric | ExperimentRatioMetric):
        query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        return ExperimentQueryRunner(query=query, team=self.team)

    @patch("products.analytics_platform.backend.lazy_computation.lazy_computation_executor.sync_execute")
    def test_ratio_sides_build_separately_and_share_jobs_with_mean_metrics(self, mock_sync_execute):
        feature_flag = self.create_feature_flag(key="ratio-metric-events-shared-jobs")
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 10),
        )
        mean_metric = ExperimentMeanMetric(source=PURCHASE_SUM)
        ratio_metric = ExperimentRatioMetric(numerator=PURCHASE_SUM, denominator=PURCHASE_COUNT)

        mean_result = self._build_runner(experiment, mean_metric)._ensure_metric_events_precomputed(
            self._build_lazy_computation_builder(experiment, feature_flag, mean_metric)
        )
        ratio_result = self._build_runner(experiment, ratio_metric)._ensure_ratio_metric_events_precomputed(
            self._build_lazy_computation_builder(experiment, feature_flag, ratio_metric)
        )

        assert mean_result.ready is True
        assert ratio_result.ready is True
        # The numerator is the same build as the mean metric, so it reused those jobs
        # without running an INSERT; the denominator's value differs, so it built its own.
        assert ratio_result.numerator.job_ids == mean_result.job_ids
        assert set(ratio_result.denominator.job_ids).isdisjoint(mean_result.job_ids)
        assert mock_sync_execute.call_count == len(mean_result.job_ids) + len(ratio_result.denominator.job_ids)

    @parameterized.expand(
        [
            ("both_sides_eligible", PURCHASE_SUM, PURCHASE_COUNT, True, None),
            ("flag_off", PURCHASE_SUM, PURCHASE_COUNT, False, "ratio_flag_off"),
            (
                "numerator_session_property",
                EventsNode(event="purchase", math=ExperimentMetricMathType.SUM, math_property="$session_duration"),
                PURCHASE_COUNT,
                True,
                "session_property_math",
            ),
            (
                "denominator_unique_group",
                PURCHASE_SUM,
                EventsNode(event="purchase", math=ExperimentMetricMathType.UNIQUE_GROUP, math_group_type_index=1),
                True,
                "unsupported_math",
            ),
        ]
    )
    def test_ratio_metric_events_precompute_gate(self, _name, numerator, denominator, flag_enabled, skip_reason):
        feature_flag = self.create_feature_flag(key="ratio-metric-events-gate")
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 10),
        )
        runner = self._build_runner(experiment, ExperimentRatioMetric(numerator=numerator, denominator=denominator))

        with patch.object(
            ExperimentQueryRunner, "_ratio_metric_events_precomputation_enabled", return_value=flag_enabled
        ):
            assert runner._metric_events_ineligibility_reason() == skip_reason
            assert runner._metric_events_precompute_applicable() is (skip_reason is None)
