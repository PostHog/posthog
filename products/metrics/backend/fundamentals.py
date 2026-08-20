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

from posthog.dataclasses import frozen

# What `p95` means when a caller doesn't spell the percentile out.
_DEFAULT_QUANTILE = 0.95


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


def plan_reduction(*, aggregation: str, metric_type: str, temporality: str = "") -> ReductionPlan:
    """Pick the two reduction steps for one aggregation on one kind of metric.

    `temporality` is the OTel `aggregation_temporality` column; gauges leave it
    empty. It matters even for the instant aggregations, because a delta sample
    is an increment rather than a reading.
    """
    try:
        spatial = _SPATIAL_BY_AGGREGATION[aggregation]
    except KeyError:
        raise ValueError(f"Unsupported aggregation: {aggregation!r}")

    quantile = _DEFAULT_QUANTILE if spatial == SpatialReducer.QUANTILE else None

    if _is_delta(temporality):
        # Delta samples are increments whatever the caller asked for, so summing
        # them over the bucket is the only reduction that keeps the total whole.
        return ReductionPlan(temporal=TemporalReducer.SUM_OVER_TIME, spatial=spatial, quantile=quantile)
    if aggregation in _COUNTER_FUNCTIONS:
        return ReductionPlan(temporal=TemporalReducer.INCREASE, spatial=spatial, quantile=quantile)
    if spatial == SpatialReducer.QUANTILE:
        return ReductionPlan(temporal=TemporalReducer.POOLED_SAMPLES, spatial=spatial, quantile=quantile)
    if spatial == SpatialReducer.AVG:
        return ReductionPlan(temporal=TemporalReducer.AVG_OVER_TIME, spatial=spatial, quantile=quantile)
    return ReductionPlan(temporal=TemporalReducer.LAST, spatial=spatial, quantile=quantile)


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


def reduce_temporal(samples: Sequence[Sample], reducer: TemporalReducer) -> float:
    """Collapse one series' samples to that series' value for the bucket."""
    if reducer in (TemporalReducer.NONE, TemporalReducer.POOLED_SAMPLES):
        raise ValueError(f"{reducer!r} has no single per-series value; apply it through a plan")
    ordered = _deduped_in_time_order(samples)
    if not ordered:
        return 0.0

    if reducer == TemporalReducer.LAST:
        return ordered[-1].value
    if reducer == TemporalReducer.SUM_OVER_TIME:
        return sum(sample.value for sample in ordered)
    if reducer == TemporalReducer.AVG_OVER_TIME:
        return sum(sample.value for sample in ordered) / len(ordered)
    if reducer == TemporalReducer.INCREASE:
        # The first sample's history is unknown, so it contributes nothing. A
        # reading below its predecessor means the counter restarted, and the
        # post-restart reading is itself the increase.
        total = 0.0
        for previous, current in zip(ordered, ordered[1:]):
            total += current.value - previous.value if current.value >= previous.value else current.value
        return total
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


def apply_plan(series_samples: Mapping[object, Sequence[Sample]], plan: ReductionPlan) -> float | None:
    """Run both reduction steps over a bucket's series and return its number."""
    if plan.temporal == TemporalReducer.NONE:
        per_series_values = [sample.value for samples in series_samples.values() for sample in samples]
    elif plan.temporal == TemporalReducer.POOLED_SAMPLES:
        per_series_values = [
            sample.value for samples in series_samples.values() for sample in _deduped_in_time_order(samples)
        ]
    else:
        per_series_values = [reduce_temporal(samples, plan.temporal) for samples in series_samples.values() if samples]
    return reduce_spatial(per_series_values, plan.spatial, quantile=plan.quantile)


def is_duplicate_invariant(series_samples: Mapping[object, Sequence[Sample]], plan: ReductionPlan) -> bool:
    """Whether re-delivering every sample leaves the bucket's number unchanged.

    Duplicating a scrape is the cheapest way to ask whether a reduction counts
    series or counts rows, and it needs no reference implementation to compare
    against — a correct plan simply returns the same number twice.
    """
    baseline = apply_plan(series_samples, plan)
    doubled = {key: [*samples, *samples] for key, samples in series_samples.items()}
    return apply_plan(doubled, plan) == baseline
