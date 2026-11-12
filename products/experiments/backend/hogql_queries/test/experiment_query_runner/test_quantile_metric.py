from typing import Any, cast

import time_machine
from posthog.test.base import flush_persons_and_events, snapshot_clickhouse_queries

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    Breakdown,
    BreakdownFilter,
    EventsNode,
    ExperimentQuantileMetric,
    ExperimentQuery,
    ExperimentQueryResponse,
    ExperimentStatsBaseValidated,
    ExperimentStatsValidationFailure,
    ExperimentVariantResultBayesian,
    ExperimentVariantResultFrequentist,
    FunnelConversionWindowTimeUnit,
)

from posthog.test.test_journeys import journeys_for

from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.hogql_queries.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest

EXPOSURE_TIME = "2024-01-02T12:00:00"


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentQuantileMetric(ExperimentQueryRunnerBaseTest):
    snapshot_replace_all_numbers = True

    def _exposure(self, variant: str, properties: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "event": "$feature_flag_called",
            "timestamp": EXPOSURE_TIME,
            "properties": {
                "$feature_flag_response": variant,
                f"$feature/{self.feature_flag.key}": variant,
                "$feature_flag": self.feature_flag.key,
                **(properties or {}),
            },
        }

    def _app_ready(self, variant: str, properties: dict[str, Any], timestamp: str = "2024-01-02T12:10:00") -> dict:
        return {
            "event": "app_ready",
            "timestamp": timestamp,
            "properties": {f"$feature/{self.feature_flag.key}": variant, **properties},
        }

    def _user(
        self, variant: str, values: list[float], exposure_properties: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        return [
            self._exposure(variant, exposure_properties),
            *(self._app_ready(variant, {"app_ready_ms": value}) for value in values),
        ]

    def _run(
        self,
        metric: ExperimentQuantileMetric,
        *,
        use_precomputation: bool = False,
        stats_config: dict[str, Any] | None = None,
    ) -> ExperimentQueryRunner:
        experiment = self.create_experiment(feature_flag=self.feature_flag)
        experiment.stats_config = stats_config or {"method": "frequentist"}
        experiment.metrics = [metric.model_dump(mode="json")]
        self._save_experiment_with_precomputation(experiment, use_precomputation)
        return ExperimentQueryRunner(
            query=ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric), team=self.team
        )

    @parameterized.expand([("direct", False), ("precomputed", True)])
    @time_machine.travel("2024-01-01T12:00:00Z", tick=False)
    @snapshot_clickhouse_queries
    def test_quantile_metric_pools_events_and_counts_users_without_events(
        self, _name: str, use_precomputation: bool
    ) -> None:
        self._setup_precomputation_test(use_precomputation)
        self.feature_flag = self.create_feature_flag()
        metric = ExperimentQuantileMetric(
            source=EventsNode(event="app_ready", math_property="app_ready_ms"), quantile=0.5
        )
        query_runner = self._run(metric, use_precomputation=use_precomputation)

        journeys_for(
            {
                "control_a": self._user("control", [3, 1, 2]),
                "control_b": self._user("control", [7, 4, 6, 5]),
                "control_c": self._user("control", [10, 8, 9]),
                "control_no_events": self._user("control", []),
                "test_a": self._user("test", [20, 10]),
                "test_b": self._user("test", [50, 30, 40]),
                "test_c": self._user("test", [60]),
            },
            self.team,
        )
        flush_persons_and_events()

        result = cast(ExperimentQueryResponse, query_runner.calculate())

        # Exposures can come from the precomputed table, but metric events are always scanned.
        assert (result.is_precomputed, query_runner.metric_events_path) == (use_precomputation, "not_applicable")
        assert result.baseline is not None
        assert result.variant_results is not None
        control = result.baseline
        test = result.variant_results[0]

        # quantileExact at level p over N values returns the sorted value at 0-based position floor(p * N):
        # position 5 of 1..10 is 6, and position 3 of [10, 20, 30, 40, 50, 60] is 40.
        assert control.quantile_grid is not None and test.quantile_grid is not None
        assert (control.quantile_grid[0], test.quantile_grid[0]) == (6, 40)
        assert len(control.quantile_grid) == 41

        # Per user (S_i, N_i): control a (3, 3), b (3, 4), c (0, 3), no_events (0, 0); test a (2, 2), b (2, 3), c (0, 1).
        assert (
            control.number_of_samples,
            control.sum,
            control.sum_squares,
            control.denominator_sum,
            control.denominator_sum_squares,
            control.numerator_denominator_sum_product,
        ) == (4, 6, 18, 10, 34, 21)
        assert (
            test.number_of_samples,
            test.sum,
            test.sum_squares,
            test.denominator_sum,
            test.denominator_sum_squares,
            test.numerator_denominator_sum_product,
        ) == (3, 4, 8, 6, 14, 10)

    @time_machine.travel("2024-01-01T12:00:00Z", tick=False)
    @snapshot_clickhouse_queries
    def test_quantile_metric_with_breakdown_counts_against_the_breakdown_and_the_whole_variant(self) -> None:
        self.feature_flag = self.create_feature_flag()
        metric = ExperimentQuantileMetric(
            source=EventsNode(event="app_ready", math_property="app_ready_ms"),
            quantile=0.5,
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")]),
        )
        query_runner = self._run(metric)

        chrome, safari, firefox = {"$browser": "Chrome"}, {"$browser": "Safari"}, {"$browser": "Firefox"}
        journeys_for(
            {
                "control_a": self._user("control", [1, 2, 3], chrome),
                "control_b": self._user("control", [4, 50], chrome),
                "control_c": self._user("control", [10, 20], safari),
                "control_d": self._user("control", [30], safari),
                "control_no_events": self._user("control", [], safari),
                "control_firefox_no_events": self._user("control", [], firefox),
                "test_a": self._user("test", [100, 200], chrome),
                "test_b": self._user("test", [300], chrome),
                "test_c": self._user("test", [50], safari),
            },
            self.team,
        )
        flush_persons_and_events()

        result = cast(ExperimentQueryResponse, query_runner.calculate())

        def stats(
            variant: ExperimentStatsBaseValidated
            | ExperimentVariantResultFrequentist
            | ExperimentVariantResultBayesian,
        ) -> tuple:
            return (
                variant.number_of_samples,
                variant.quantile_grid[0] if variant.quantile_grid else None,
                variant.sum,
                variant.sum_squares,
                variant.denominator_sum,
                variant.denominator_sum_squares,
                variant.numerator_denominator_sum_product,
            )

        assert result.baseline is not None and result.variant_results is not None
        assert result.breakdown_results is not None
        # (users, quantile, Σ S_i, Σ S_i², Σ N_i, Σ N_i², Σ S_i·N_i). The overall control median is 10, and in
        # Chrome and Safari it is 3 and 20, so control a counts 3 events, b 1 and c 1 against the overall median.
        assert {v.key: stats(v) for v in [result.baseline, *result.variant_results]} == {
            "control": (6, 10, 5, 11, 8, 18, 13),
            "test": (3, 200, 3, 5, 4, 6, 5),
        }
        assert {
            tuple(breakdown.breakdown_value): {v.key: stats(v) for v in [breakdown.baseline, *breakdown.variants]}
            for breakdown in result.breakdown_results
        } == {
            ("Chrome",): {"control": (2, 3, 3, 9, 5, 13, 9), "test": (2, 200, 2, 4, 3, 5, 4)},
            ("Safari",): {"control": (3, 20, 2, 4, 3, 5, 4), "test": (1, 50, 1, 1, 1, 1, 1)},
            ("Firefox",): {"control": (1, None, 0, 0, 0, 0, 0), "test": (0, None, 0, 0, None, None, None)},
        }

    @parameterized.expand(
        [
            ("event_without_the_property", {}, "2024-01-02T12:10:00", None),
            ("event_with_a_non_numeric_value", {"app_ready_ms": "fast"}, "2024-01-02T12:10:00", None),
            ("event_after_the_conversion_window", {"app_ready_ms": 1000}, "2024-01-02T14:00:00", 1),
            ("event_before_the_exposure", {"app_ready_ms": 1000}, "2024-01-02T11:00:00", None),
        ]
    )
    @time_machine.travel("2024-01-01T12:00:00Z", tick=False)
    def test_quantile_metric_ignores_events_without_a_value_in_the_window(
        self, _name: str, properties: dict[str, Any], timestamp: str, conversion_window_hours: int | None
    ) -> None:
        self.feature_flag = self.create_feature_flag()
        window: dict[str, Any] = (
            {
                "conversion_window": conversion_window_hours,
                "conversion_window_unit": FunnelConversionWindowTimeUnit.HOUR,
            }
            if conversion_window_hours
            else {}
        )
        metric = ExperimentQuantileMetric(
            source=EventsNode(event="app_ready", math_property="app_ready_ms"), quantile=0.5, **window
        )
        query_runner = self._run(metric)

        journeys_for(
            {
                "control_a": [*self._user("control", [1, 2, 3]), self._app_ready("control", properties, timestamp)],
                "test_a": self._user("test", [1, 2, 3]),
            },
            self.team,
        )
        flush_persons_and_events()

        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.baseline is not None and result.baseline.quantile_grid is not None
        assert (result.baseline.denominator_sum, result.baseline.quantile_grid[0]) == (3, 2)

    @time_machine.travel("2024-01-01T12:00:00Z", tick=False)
    def test_quantile_metric_counts_ties_and_keeps_a_variant_without_events(self) -> None:
        self.feature_flag = self.create_feature_flag()
        metric = ExperimentQuantileMetric(
            source=EventsNode(event="app_ready", math_property="app_ready_ms"), quantile=0.5
        )
        query_runner = self._run(metric)

        journeys_for(
            {
                # Control pools 1, 5, 5, 5, 5, 9, 9, 9, so the median is 5 and four events tie with it.
                "control_a": self._user("control", [5, 5, 5]),
                "control_b": self._user("control", [1, 5, 9]),
                "control_c": self._user("control", [9, 9]),
                "test_a": self._user("test", []),
                "test_b": self._user("test", []),
            },
            self.team,
        )
        flush_persons_and_events()

        result = cast(ExperimentQueryResponse, query_runner.calculate())

        control = result.baseline
        assert control is not None and control.quantile_grid is not None
        # Per user S_i: a 3, b 2 (1 and 5), c 0. A strict comparison gives a 0 and b 1.
        assert (control.quantile_grid[0], control.sum, control.denominator_sum) == (5, 5, 8)

        assert result.variant_results is not None
        test = result.variant_results[0]
        assert (test.number_of_samples, test.sum, test.denominator_sum) == (2, 0, 0)
        assert not test.quantile_grid
        assert test.validation_failures is not None
        assert ExperimentStatsValidationFailure.NOT_ENOUGH_METRIC_DATA in test.validation_failures

    @parameterized.expand(
        [
            ("frequentist", {"method": "frequentist"}),
            (
                "frequentist_sequential",
                {"method": "frequentist", "frequentist": {"sequential_testing_enabled": True}},
            ),
            ("bayesian", {"method": "bayesian"}),
        ]
    )
    @time_machine.travel("2024-01-01T12:00:00Z", tick=False)
    def test_quantile_metric_reaches_inference_with_enough_users(
        self, _name: str, stats_config: dict[str, Any]
    ) -> None:
        self.feature_flag = self.create_feature_flag()
        metric = ExperimentQuantileMetric(
            source=EventsNode(event="app_ready", math_property="app_ready_ms"), quantile=0.5
        )
        query_runner = self._run(metric, stats_config=stats_config)

        journeys: dict[str, list[dict[str, Any]]] = {}
        for i in range(60):
            journeys[f"control_{i}"] = self._user("control", [i + 1, i + 61])
            journeys[f"test_{i}"] = self._user("test", [i + 101, i + 161])
        journeys_for(journeys, self.team)
        flush_persons_and_events()

        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.baseline is not None and result.baseline.quantile_grid is not None
        assert result.variant_results is not None
        test = result.variant_results[0]
        assert test.quantile_grid is not None
        # Position floor(0.5 * 120) = 60 of the sorted values is 61 for control and 161 for test.
        assert (result.baseline.quantile_grid[0], test.quantile_grid[0]) == (61, 161)
        assert (result.baseline.validation_failures, test.validation_failures) == ([], [])

        if stats_config["method"] == "frequentist":
            interval = cast(ExperimentVariantResultFrequentist, test).confidence_interval
        else:
            interval = cast(ExperimentVariantResultBayesian, test).credible_interval
        assert interval is not None
        # The relative effect is (161 - 61) / 61, about 1.64, and the test median is above the control median.
        assert 0 < interval[0] < 1.64 < interval[1]
        assert test.significant is True
