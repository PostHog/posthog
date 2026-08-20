import datetime as dt

import pytest

from parameterized import parameterized

from products.metrics.backend.fundamentals import (
    ReductionPlan,
    Sample,
    SpatialReducer,
    TemporalReducer,
    is_duplicate_invariant,
    plan_reduction,
    reduce_spatial,
    reduce_temporal,
)

BUCKET = dt.datetime(2026, 1, 1, 0, 0, 0, tzinfo=dt.UTC)


def _samples(*values: float, step_seconds: int = 30) -> list[Sample]:
    return [Sample(timestamp=BUCKET + dt.timedelta(seconds=i * step_seconds), value=v) for i, v in enumerate(values)]


class TestPlanReduction:
    @parameterized.expand(
        [
            # A gauge sample is a re-reading, so the bucket's current value is the last one.
            ("gauge_sum", "sum", "gauge", "", TemporalReducer.LAST, SpatialReducer.SUM),
            ("gauge_avg", "avg", "gauge", "", TemporalReducer.LAST, SpatialReducer.AVG),
            ("gauge_count", "count", "gauge", "", TemporalReducer.LAST, SpatialReducer.COUNT_SERIES),
            ("gauge_p95", "p95", "gauge", "", TemporalReducer.LAST, SpatialReducer.QUANTILE),
            # A cumulative counter carries an absolute odometer reading.
            ("cumulative_sum", "sum", "sum", "cumulative", TemporalReducer.LAST, SpatialReducer.SUM),
            ("cumulative_increase", "increase", "sum", "cumulative", TemporalReducer.INCREASE, SpatialReducer.SUM),
            ("cumulative_rate", "rate", "sum", "cumulative", TemporalReducer.INCREASE, SpatialReducer.SUM),
            # A delta sample IS an increment, so the bucket total is their sum. Taking the
            # last sample here keeps one increment and discards the rest.
            ("delta_sum", "sum", "sum", "delta", TemporalReducer.SUM_OVER_TIME, SpatialReducer.SUM),
            ("delta_increase", "increase", "sum", "delta", TemporalReducer.SUM_OVER_TIME, SpatialReducer.SUM),
        ]
    )
    def test_plan_maps_type_and_temporality(
        self,
        _name: str,
        aggregation: str,
        metric_type: str,
        temporality: str,
        expected_temporal: TemporalReducer,
        expected_spatial: SpatialReducer,
    ) -> None:
        plan = plan_reduction(aggregation=aggregation, metric_type=metric_type, temporality=temporality)
        assert plan.temporal == expected_temporal
        assert plan.spatial == expected_spatial


class TestTemporalReduction:
    def test_last_uses_latest_timestamp_not_largest_value(self) -> None:
        # A falling gauge: the peak is stale, the current reading is the tail.
        assert reduce_temporal(_samples(100, 50, 10), TemporalReducer.LAST) == 10

    def test_sum_over_time_dedupes_duplicate_timestamps(self) -> None:
        # Two rows at one timestamp are one increment delivered twice, not two increments.
        duplicated = [*_samples(3, 4), Sample(timestamp=BUCKET, value=3)]
        assert reduce_temporal(duplicated, TemporalReducer.SUM_OVER_TIME) == 7

    def test_increase_corrects_counter_reset(self) -> None:
        # 100 -> 120 is +20; the drop to 5 is a restart, so 5 itself is the increase; 5 -> 25 is +20.
        assert reduce_temporal(_samples(100, 120, 5, 25), TemporalReducer.INCREASE) == 45

    def test_increase_ignores_history_before_the_first_sample(self) -> None:
        assert reduce_temporal(_samples(100), TemporalReducer.INCREASE) == 0


class TestSpatialReduction:
    @parameterized.expand(
        [
            ("sum", SpatialReducer.SUM, 30.0),
            ("avg", SpatialReducer.AVG, 10.0),
            ("min", SpatialReducer.MIN, 5.0),
            ("max", SpatialReducer.MAX, 15.0),
            ("count_series", SpatialReducer.COUNT_SERIES, 3.0),
        ]
    )
    def test_combines_one_value_per_series(self, _name: str, reducer: SpatialReducer, expected: float) -> None:
        assert reduce_spatial([10.0, 5.0, 15.0], reducer) == expected

    def test_quantile_runs_over_series_values(self) -> None:
        assert reduce_spatial([1.0, 2.0, 3.0, 4.0], SpatialReducer.QUANTILE, quantile=0.5) == pytest.approx(2.5)

    def test_empty_bucket_has_no_value(self) -> None:
        assert reduce_spatial([], SpatialReducer.SUM) is None


class TestDuplicateSampleInvariance:
    """Re-delivering a scrape must not move the number. This is the property that
    both known aggregation bugs violate, in opposite directions."""

    @parameterized.expand(
        [
            ("gauge_sum", "sum", "gauge", ""),
            ("gauge_avg", "avg", "gauge", ""),
            ("gauge_p95", "p95", "gauge", ""),
            ("gauge_count", "count", "gauge", ""),
            ("delta_sum", "sum", "sum", "delta"),
            ("cumulative_increase", "increase", "sum", "cumulative"),
        ]
    )
    def test_planned_reduction_is_invariant(
        self, _name: str, aggregation: str, metric_type: str, temporality: str
    ) -> None:
        plan = plan_reduction(aggregation=aggregation, metric_type=metric_type, temporality=temporality)
        series = {"a": _samples(5, 7, 9), "b": _samples(2, 4)}
        assert is_duplicate_invariant(series, plan) is True

    @parameterized.expand(
        [
            ("sum", SpatialReducer.SUM),
            ("count_series", SpatialReducer.COUNT_SERIES),
        ]
    )
    def test_detects_a_plan_with_no_temporal_step(self, _name: str, spatial: SpatialReducer) -> None:
        # NONE routes every raw sample to the spatial reducer, so the answer tracks the
        # scrape rate rather than the data.
        plan = ReductionPlan(temporal=TemporalReducer.NONE, spatial=spatial)
        assert is_duplicate_invariant({"a": _samples(5, 5, 5)}, plan) is False
