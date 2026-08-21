import datetime as dt

import pytest

from parameterized import parameterized

from products.metrics.backend.fundamentals import (
    ReductionPlan,
    Sample,
    SpatialReducer,
    TemporalReducer,
    apply_plan,
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
            ("gauge_sum", "sum", "gauge", "", TemporalReducer.LAST, SpatialReducer.SUM, 1.0),
            # A gauge that moves inside the bucket has a meaningful mean, so the
            # per-series step averages over time rather than keeping one reading.
            ("gauge_avg", "avg", "gauge", "", TemporalReducer.AVG_OVER_TIME, SpatialReducer.AVG, 1.0),
            ("gauge_count", "count", "gauge", "", TemporalReducer.LAST, SpatialReducer.COUNT_SERIES, 1.0),
            # A percentile describes a distribution, so it needs the readings
            # themselves rather than one summary number per series.
            ("gauge_p95", "p95", "gauge", "", TemporalReducer.POOLED_SAMPLES, SpatialReducer.QUANTILE, 1.0),
            # A cumulative counter carries an absolute odometer reading.
            ("cumulative_sum", "sum", "sum", "cumulative", TemporalReducer.LAST, SpatialReducer.SUM, 1.0),
            (
                "cumulative_increase",
                "increase",
                "sum",
                "cumulative",
                TemporalReducer.INCREASE,
                SpatialReducer.SUM,
                1.0,
            ),
            # Same two reduction steps as `increase`; only the divisor separates them.
            ("cumulative_rate", "rate", "sum", "cumulative", TemporalReducer.INCREASE, SpatialReducer.SUM, 300.0),
            # A delta sample IS an increment, so the bucket total is their sum. Taking the
            # last sample here keeps one increment and discards the rest.
            ("delta_sum", "sum", "sum", "delta", TemporalReducer.SUM_OVER_TIME, SpatialReducer.SUM, 1.0),
            ("delta_increase", "increase", "sum", "delta", TemporalReducer.SUM_OVER_TIME, SpatialReducer.SUM, 1.0),
            ("delta_rate", "rate", "sum", "delta", TemporalReducer.SUM_OVER_TIME, SpatialReducer.SUM, 300.0),
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
        expected_divisor: float,
    ) -> None:
        plan = plan_reduction(
            aggregation=aggregation, metric_type=metric_type, temporality=temporality, interval_seconds=300
        )
        assert plan.temporal == expected_temporal
        assert plan.spatial == expected_spatial
        assert plan.divisor == expected_divisor


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

    def test_avg_over_time_keeps_the_whole_bucket_not_just_the_tail(self) -> None:
        # A queue that spiked to 240 and settled at 8 did not average 8.
        assert reduce_temporal(_samples(6, 240, 5, 210, 7, 8), TemporalReducer.AVG_OVER_TIME) == pytest.approx(
            79.33, abs=0.01
        )


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

    @parameterized.expand([("sum", SpatialReducer.SUM), ("count_series", SpatialReducer.COUNT_SERIES)])
    def test_empty_bucket_has_no_value(self, _name: str, reducer: SpatialReducer) -> None:
        # The runner returns no row for an empty bucket, so a reference that
        # returned 0 here would report every empty bucket as a disagreement.
        assert reduce_spatial([], reducer) is None


class TestPooledQuantile:
    def test_percentile_reads_the_samples_rather_than_one_value_per_series(self) -> None:
        # One series that swings inside the bucket still has a tail.
        plan = plan_reduction(aggregation="p95", metric_type="gauge")
        spiky = {"a": _samples(6, 240, 5, 210, 7, 8)}
        assert apply_plan(spiky, plan) == pytest.approx(232.5)

    def test_percentile_pools_across_series(self) -> None:
        plan = plan_reduction(aggregation="p95", metric_type="gauge")
        pooled = apply_plan({"a": _samples(1, 2), "b": _samples(3, 4)}, plan)
        assert pooled == pytest.approx(_quantile_of([1.0, 2.0, 3.0, 4.0]))


class TestRateNormalization:
    @parameterized.expand(
        [
            # A counter climbing 60 over a five-minute bucket is 0.2/s.
            ("rate_is_per_second", "rate", 0.2),
            ("increase_is_the_total", "increase", 60.0),
        ]
    )
    def test_only_rate_divides_by_the_bucket_length(self, _name: str, aggregation: str, expected: float) -> None:
        # The runner divides a rate by the bucket length, so a reference that
        # skips it disagrees with every correct rate chart by that length.
        plan = plan_reduction(
            aggregation=aggregation, metric_type="sum", temporality="cumulative", interval_seconds=300
        )
        assert apply_plan({"a": _samples(10, 70)}, plan) == pytest.approx(expected)

    def test_rate_refuses_to_plan_without_a_bucket_length(self) -> None:
        # Defaulting the interval would silently plot an increase as a rate.
        with pytest.raises(ValueError):
            plan_reduction(aggregation="rate", metric_type="sum", temporality="cumulative")


def _quantile_of(values: list[float]) -> float:
    position = 0.95 * (len(values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    weight = position - lower
    return values[lower] * (1 - weight) + values[upper] * weight


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
