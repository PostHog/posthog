"""
Exported enums and constants for metrics.

These appear in the contract dataclasses (contracts.py) and are the
vocabulary other products / the presentation layer use to build metric
queries. Framework-free: no Django, no DRF.
"""

from __future__ import annotations

from enum import StrEnum


class AttributeScope(StrEnum):
    """Where a label lives on a `metrics1` row.

    - RESOURCE: `resource_attributes` (set once per scrape target, e.g.
      `service.name`, `k8s.pod.name`).
    - ATTRIBUTE: per-data-point `attributes` (the alias that strips the
      5-char `_str` type tag, e.g. `http.method`).
    - AUTO: resource first, fall back to attribute. ClickHouse map lookups
      return '' for missing keys, so the fallback compares against '' — you
      cannot meaningfully match "equals empty string" in AUTO scope; use an
      explicit scope for that edge case.
    """

    RESOURCE = "resource"
    ATTRIBUTE = "attribute"
    AUTO = "auto"


class FilterOp(StrEnum):
    """Comparison operators for a label filter."""

    EQ = "eq"
    NEQ = "neq"
    REGEX = "regex"
    NOT_REGEX = "not_regex"


class MetricType(StrEnum):
    """The OTel metric type a clause targets. Series identity includes the
    type — one name can exist as both a counter and a gauge — so queries
    constrain it to avoid blending distinct series. Values match what the
    ingest writes to `metric_type` (rust/capture-logs `flatten_metric`)."""

    GAUGE = "gauge"
    SUM = "sum"
    HISTOGRAM = "histogram"
    EXPONENTIAL_HISTOGRAM = "exponential_histogram"
    SUMMARY = "summary"


class MetricAggregation(StrEnum):
    """How a clause collapses the values in each time bucket into one number.

    Instant aggregations operate on the values that fell in the bucket:
    SUM, AVG, COUNT, MIN, MAX, QUANTILE.

    Counter functions operate on the change across the bucket (cumulative
    counters get reset-corrected; deltas are summed): RATE, INCREASE.

    HISTOGRAM_QUANTILE reads the `histogram_bounds`/`histogram_counts`
    arrays rather than the scalar `value`.

    QUANTILE and HISTOGRAM_QUANTILE require the clause's `quantile` field.
    """

    SUM = "sum"
    AVG = "avg"
    COUNT = "count"
    MIN = "min"
    MAX = "max"
    QUANTILE = "quantile"
    RATE = "rate"
    INCREASE = "increase"
    HISTOGRAM_QUANTILE = "histogram_quantile"

    @property
    def needs_quantile(self) -> bool:
        return self in (MetricAggregation.QUANTILE, MetricAggregation.HISTOGRAM_QUANTILE)

    @property
    def is_counter_function(self) -> bool:
        return self in (MetricAggregation.RATE, MetricAggregation.INCREASE)
