from datetime import datetime
from typing import cast

from freezegun import freeze_time
from posthog.test.base import _create_event, _create_person, flush_persons_and_events, snapshot_clickhouse_queries

from django.test import override_settings

from posthog.schema import (
    EventsNode,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentQuery,
    ExperimentQueryResponse,
    ExperimentStatsValidationFailure,
    ExperimentVariantResultFrequentist,
    NewExperimentQueryResponse,
)

from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.hogql_queries.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest


@override_settings(IN_UNIT_TESTING=True)
class TestFrequentistMethod(ExperimentQueryRunnerBaseTest):
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_frequentist_property_sum_metric(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.SUM,
                math_property="amount",
            ),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        self.create_standard_test_events(feature_flag)

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)

        result = cast(NewExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        test_variant = result.variant_results[0]
        assert isinstance(test_variant, ExperimentVariantResultFrequentist)

        self.assertEqual(control_variant.sum, 20)
        self.assertEqual(test_variant.sum, 20)
        self.assertEqual(control_variant.number_of_samples, 10)
        self.assertEqual(test_variant.number_of_samples, 10)
        self.assertEqual(test_variant.confidence_interval, None)
        self.assertFalse(test_variant.significant)
        self.assertEqual(test_variant.p_value, None)
        self.assertEqual(test_variant.validation_failures, [ExperimentStatsValidationFailure.NOT_ENOUGH_EXPOSURES])

    def _populate_purchases(self, feature_flag, samples_per_variant: int = 60) -> None:
        feature_flag_property = f"$feature/{feature_flag.key}"
        for variant, treatment_effect in [("control", 0), ("test", 5)]:
            for i in range(samples_per_variant):
                distinct_id = f"{feature_flag.key}_{variant}_{i}"
                _create_person(distinct_ids=[distinct_id], team_id=self.team.pk)
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=distinct_id,
                    timestamp="2020-01-02T12:00:00Z",
                    properties={
                        feature_flag_property: variant,
                        "$feature_flag_response": variant,
                        "$feature_flag": feature_flag.key,
                    },
                )
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=distinct_id,
                    timestamp="2020-01-02T13:00:00Z",
                    properties={feature_flag_property: variant, "amount": 10 + treatment_effect + (i % 3)},
                )

    def _run_metric(self, experiment) -> ExperimentQueryResponse:
        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.SUM,
                math_property="amount",
            ),
        )
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()
        query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        return cast(ExperimentQueryResponse, ExperimentQueryRunner(query=query, team=self.team).calculate())

    @freeze_time("2020-01-03T12:00:00Z")
    def test_sequential_testing_widens_ci_versus_fixed_horizon(self) -> None:
        # Run identical data through fixed-horizon then sequential frequentist; verify
        # the sequential CI is strictly wider end-to-end through the query runner.
        experiment_start = datetime(2020, 1, 1, 0, 0, 0)
        experiment_end = datetime(2020, 1, 5, 0, 0, 0)

        feature_flag_fixed = self.create_feature_flag(key="test-experiment-fixed")
        experiment_fixed = self.create_experiment(
            name="fixed",
            feature_flag=feature_flag_fixed,
            start_date=experiment_start,
            end_date=experiment_end,
        )
        experiment_fixed.stats_config = {"method": "frequentist"}
        experiment_fixed.save()
        self._populate_purchases(feature_flag_fixed)

        feature_flag_seq = self.create_feature_flag(key="test-experiment-seq")
        experiment_seq = self.create_experiment(
            name="seq",
            feature_flag=feature_flag_seq,
            start_date=experiment_start,
            end_date=experiment_end,
        )
        experiment_seq.stats_config = {
            "method": "frequentist",
            "frequentist": {"sequential_testing_enabled": True, "sequential_tuning_parameter": 5000},
        }
        experiment_seq.save()
        self._populate_purchases(feature_flag_seq)

        flush_persons_and_events()

        fixed_result = self._run_metric(experiment_fixed)
        seq_result = self._run_metric(experiment_seq)

        assert fixed_result.variant_results is not None and seq_result.variant_results is not None
        fixed_variant = cast(ExperimentVariantResultFrequentist, fixed_result.variant_results[0])
        seq_variant = cast(ExperimentVariantResultFrequentist, seq_result.variant_results[0])

        assert fixed_variant.confidence_interval is not None
        assert seq_variant.confidence_interval is not None

        fixed_width = fixed_variant.confidence_interval[1] - fixed_variant.confidence_interval[0]
        seq_width = seq_variant.confidence_interval[1] - seq_variant.confidence_interval[0]

        self.assertGreater(seq_width, fixed_width)
