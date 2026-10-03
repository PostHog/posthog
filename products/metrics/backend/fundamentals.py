"""The reduction rules every metric aggregation has to follow, as data.

A bucket is not a bag of numbers. It holds a set of *series*, and each series
holds a set of *samples*. Collapsing it to one number is therefore two ordered
steps, never one:

    value(bucket) = spatial( over each series: temporal(its samples) )

`plan_reduction` picks both steps from the metric's type and temporality, which
is the part that is easy to get wrong by hand: a gauge sample is a re-reading
(take the last), a cumulative counter sample is an odometer (diff it), and a
delta counter sample is itself an increment (add them up). Applying one reducer
to all three silently returns a number that tracks the scrape rate instead of
the data.

The reducers here are deliberately pure and independent of the HogQL builders in
`metric_query_runner`, so they can serve as the reference a query result is
checked against rather than a second copy of the same assumptions.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import TypeVar

from posthog.dataclasses import frozen

# What `p95` means when a caller doesn't spell the percentile out.
_DEFAULT_QUANTILE = 0.95

# The reducers never read a series key; it only has to identify the series.
K = TypeVar("K")


@frozen
class Sample:
    """One raw reading of one series."""

    timestamp: dt.datetime
    value: float


class TemporalReducer(StrEnum):
    """How one series' samples collapse to that series' value for the bucket."""

    # No temporal step: every raw sample flows into the spatial reducer. This is
    # the shape of the bug this module exists to catch, kept nameable so a
    # decomposition can report it rather than only failing a check.
    NONE = "none"
    # Gauges under an instant aggregation: the bucket's value is the most
    # recent reading, matching PromQL's instant vector.
    LAST = "last"
    # Gauges under an average: the readings inside the bucket are all real
    # observations, so the series' value for the bucket is their mean.
    AVG_OVER_TIME = "avg_over_time"
    # Percentiles: there is no per-series step at all. A percentile describes a
    # distribution, and collapsing each series first would compute a percentile
    # of summaries, which is not a percentile of anything. Samples are deduped
    # by timestamp and pooled instead.
    POOLED_SAMPLES = "pooled_samples"
    # Delta counters: each sample is an increment already.
    SUM_OVER_TIME = "sum_over_time"
    # Cumulative counters: diff consecutive readings, treating a drop as a restart.
    INCREASE = "increase"


class SpatialReducer(StrEnum):
    """How one value per series collapses to the bucket's number."""

    SUM = "sum"
    AVG = "avg"
    MIN = "min"
    MAX = "max"
    QUANTILE = "quantile"
    COUNT_SERIES = "count_series"


@frozen
class ReductionPlan:
    temporal: TemporalReducer
    spatial: SpatialReducer
    quantile: float | None = None
    # `rate` is an increase per second, so its bucket total is divided by the
    # time that total accumulated over. Every other aggregation plots the total.
    divisor: float = 1.0


_SPATIAL_BY_AGGREGATION: dict[str, SpatialReducer] = {
    "sum": SpatialReducer.SUM,
    "avg": SpatialReducer.AVG,
    "min": SpatialReducer.MIN,
    "max": SpatialReducer.MAX,
    "count": SpatialReducer.COUNT_SERIES,
    "p95": SpatialReducer.QUANTILE,
    "quantile": SpatialReducer.QUANTILE,
    "rate": SpatialReducer.SUM,
    "increase": SpatialReducer.SUM,
}

_COUNTER_FUNCTIONS = frozenset({"rate", "increase"})


def _is_delta(temporality: str) -> bool:
    return temporality == "delta"


def _rate_divisor(aggregation: str, interval_seconds: float | None) -> float:
    """How long the bucket's total accumulated over, for the aggregations that
    plot a per-second figure rather than the total itself.

    Refusing to default the interval keeps a plan built without one from
    quietly reporting an increase where a rate was asked for — off by the
    bucket length, which is the whole difference between the two.
    """
    if aggregation != "rate":
        return 1.0
    if interval_seconds is None or interval_seconds <= 0:
        raise ValueError("rate is a per-second figure, so it needs a positive interval_seconds")
    return float(interval_seconds)


def plan_reduction(
    *,
    aggregation: str,
    metric_type: str,
    temporality: str = "",
    interval_seconds: float | None = None,
) -> ReductionPlan:
    """Pick the two reduction steps for one aggregation on one kind of metric.

    `temporality` is the OTel `aggregation_temporality` column; gauges leave it
    empty. It matters even for the instant aggregations, because a delta sample
    is an increment rather than a reading.

    `interval_seconds` is the bucket's width, which only `rate` needs.
    """
    try:
        spatial = _SPATIAL_BY_AGGREGATION[aggregation]
    except KeyError:
        raise ValueError(f"Unsupported aggregation: {aggregation!r}")

    quantile = _DEFAULT_QUANTILE if spatial == SpatialReducer.QUANTILE else None
    divisor = _rate_divisor(aggregation, interval_seconds)

    if _is_delta(temporality):
        # Delta samples are increments whatever the caller asked for, so summing
        # them over the bucket is the only reduction that keeps the total whole.
        return ReductionPlan(
            temporal=TemporalReducer.SUM_OVER_TIME, spatial=spatial, quantile=quantile, divisor=divisor
        )
    if aggregation in _COUNTER_FUNCTIONS:
        return ReductionPlan(temporal=TemporalReducer.INCREASE, spatial=spatial, quantile=quantile, divisor=divisor)
    if spatial == SpatialReducer.QUANTILE:
        return ReductionPlan(
            temporal=TemporalReducer.POOLED_SAMPLES, spatial=spatial, quantile=quantile, divisor=divisor
        )
    if spatial == SpatialReducer.AVG:
        return ReductionPlan(
            temporal=TemporalReducer.AVG_OVER_TIME, spatial=spatial, quantile=quantile, divisor=divisor
        )
    return ReductionPlan(temporal=TemporalReducer.LAST, spatial=spatial, quantile=quantile, divisor=divisor)


def _deduped_in_time_order(samples: Sequence[Sample]) -> list[Sample]:
    """One reading per timestamp, oldest first.

    A series re-delivered by the collector arrives as two rows sharing a
    timestamp. That is one observation, so anything that adds samples together
    has to collapse it first or the total moves with delivery luck.
    """
    by_timestamp: dict[dt.datetime, Sample] = {}
    for sample in sorted(samples, key=lambda s: s.timestamp):
        by_timestamp.setdefault(sample.timestamp, sample)
    return list(by_timestamp.values())


def reduce_temporal(samples: Sequence[Sample], reducer: TemporalReducer) -> float | None:
    """Collapse one series' samples to that series' value for the bucket.

    Returns None when the value is unknowable: a lone cumulative reading has
    no predecessor to diff against, and 0 would read as a flat counter.
    """
    if reducer in (TemporalReducer.NONE, TemporalReducer.POOLED_SAMPLES):
        raise ValueError(f"{reducer!r} has no single per-series value; apply it through a plan")
    ordered = _deduped_in_time_order(samples)
    if reducer == TemporalReducer.INCREASE:
        # A reading below its predecessor means the counter restarted, and the
        # post-restart reading is itself the increase.
        if len(ordered) < 2:
            return None
        total = 0.0
        for previous, current in zip(ordered, ordered[1:]):
            total += current.value - previous.value if current.value >= previous.value else current.value
        return total
    if not ordered:
        return 0.0

    if reducer == TemporalReducer.LAST:
        return ordered[-1].value
    if reducer == TemporalReducer.SUM_OVER_TIME:
        return sum(sample.value for sample in ordered)
    if reducer == TemporalReducer.AVG_OVER_TIME:
        return sum(sample.value for sample in ordered) / len(ordered)
    raise ValueError(f"Unsupported temporal reducer: {reducer!r}")


def _quantile(sorted_values: Sequence[float], quantile: float) -> float:
    """Linear interpolation between the closest ranks."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = quantile * (len(sorted_values) - 1)
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(sorted_values) - 1)
    weight = position - lower_index
    return sorted_values[lower_index] * (1 - weight) + sorted_values[upper_index] * weight


def reduce_spatial(values: Sequence[float], reducer: SpatialReducer, *, quantile: float | None = None) -> float | None:
    """Combine one value per series into the bucket's number.

    Returns None for an empty bucket, which consumers render as a gap rather
    than as a zero.
    """
    # An empty bucket has no value at all, including no series count. Returning
    # 0 here would make every gap look like a real zero.
    if not values:
        return None
    if reducer == SpatialReducer.COUNT_SERIES:
        return float(len(values))

    if reducer == SpatialReducer.SUM:
        return sum(values)
    if reducer == SpatialReducer.AVG:
        return sum(values) / len(values)
    if reducer == SpatialReducer.MIN:
        return min(values)
    if reducer == SpatialReducer.MAX:
        return max(values)
    if reducer == SpatialReducer.QUANTILE:
        return _quantile(sorted(values), quantile if quantile is not None else _DEFAULT_QUANTILE)
    raise ValueError(f"Unsupported spatial reducer: {reducer!r}")


def apply_plan(series_samples: Mapping[K, Sequence[Sample]], plan: ReductionPlan) -> float | None:
    """Run both reduction steps over a bucket's series and return its number."""
    if plan.temporal == TemporalReducer.NONE:
        per_series_values = [sample.value for samples in series_samples.values() for sample in samples]
    elif plan.temporal == TemporalReducer.POOLED_SAMPLES:
        per_series_values = [
            sample.value for samples in series_samples.values() for sample in _deduped_in_time_order(samples)
        ]
    else:
        # An unknowable series value contributes nothing rather than a fake 0,
        # and a bucket holding only unknowns has no value at all.
        reduced = (reduce_temporal(samples, plan.temporal) for samples in series_samples.values() if samples)
        per_series_values = [value for value in reduced if value is not None]
    value = reduce_spatial(per_series_values, plan.spatial, quantile=plan.quantile)
    # An empty bucket has no number, and normalizing None would invent one.
    return value if value is None else value / plan.divisor


def is_duplicate_invariant(series_samples: Mapping[K, Sequence[Sample]], plan: ReductionPlan) -> bool:
    """Whether re-delivering every sample leaves the bucket's number unchanged.

    Duplicating a scrape is the cheapest way to ask whether a reduction counts
    series or counts rows, and it needs no reference implementation to compare
    against — a correct plan simply returns the same number twice.
    """
    baseline = apply_plan(series_samples, plan)
    doubled = {key: [*samples, *samples] for key, samples in series_samples.items()}
    return apply_plan(doubled, plan) == baseline
