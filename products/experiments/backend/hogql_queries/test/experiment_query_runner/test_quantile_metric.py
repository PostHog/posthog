from typing import Any, cast

import time_machine
from posthog.test.base import flush_persons_and_events, snapshot_clickhouse_queries

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    EventsNode,
    ExperimentQuantileMetric,
    ExperimentQuery,
    ExperimentQueryResponse,
    FunnelConversionWindowTimeUnit,
)

from posthog.test.test_journeys import journeys_for

from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.hogql_queries.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest

EXPOSURE_TIME = "2024-01-02T12:00:00"


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentQuantileMetric(ExperimentQueryRunnerBaseTest):
    snapshot_replace_all_numbers = True

    def _exposure(self, variant: str) -> dict[str, Any]:
        return {
            "event": "$feature_flag_called",
            "timestamp": EXPOSURE_TIME,
            "properties": {
                "$feature_flag_response": variant,
                f"$feature/{self.feature_flag.key}": variant,
                "$feature_flag": self.feature_flag.key,
            },
        }

    def _app_ready(self, variant: str, properties: dict[str, Any], timestamp: str = "2024-01-02T12:10:00") -> dict:
        return {
            "event": "app_ready",
            "timestamp": timestamp,
            "properties": {f"$feature/{self.feature_flag.key}": variant, **properties},
        }

    def _user(self, variant: str, values: list[float]) -> list[dict[str, Any]]:
        return [self._exposure(variant), *(self._app_ready(variant, {"app_ready_ms": value}) for value in values)]

    def _run(self, metric: ExperimentQuantileMetric, *, use_precomputation: bool = False) -> ExperimentQueryRunner:
        experiment = self.create_experiment(feature_flag=self.feature_flag)
        experiment.stats_config = {"method": "frequentist"}
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
                # Control pools 10 events with values 1..10 over three users, plus one user without events.
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

    @parameterized.expand(
        [
            ("event_without_the_property", {}, "2024-01-02T12:10:00", None),
            ("event_with_a_non_numeric_value", {"app_ready_ms": "fast"}, "2024-01-02T12:10:00", None),
            ("event_after_the_conversion_window", {"app_ready_ms": 1000}, "2024-01-02T14:00:00", 1),
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
