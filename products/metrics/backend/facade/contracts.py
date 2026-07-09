"""
Contract types for metrics.

Stable, framework-free frozen dataclasses that define what this
product exposes to the rest of the codebase.

Characteristics:
- No Django imports
- Immutable (frozen=True)
- Used by facade as inputs/outputs

Do NOT depend on Django models, DRF serializers, or request objects.

These define the query wire shape used by the viewer, the dashboard
widget, and (later) alerting. The response is always a list of
`MetricSeries` — a single ungrouped query returns one series with empty
labels, so consumers never branch on "single vs multi series".
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .enums import AttributeScope, FilterOp, MetricAggregation

# Each clause runs its own ClickHouse query on the shared logs cluster, so
# the clause count per request is hard-capped.
MAX_CLAUSES_PER_QUERY = 10


@dataclass(frozen=True, slots=True)
class MetricFilter:
    """A single label predicate on a clause."""

    key: str
    op: FilterOp
    value: str
    scope: AttributeScope = AttributeScope.AUTO


@dataclass(frozen=True, slots=True)
class MetricGroupBy:
    """One label to split a clause's result into separate series by."""

    key: str
    scope: AttributeScope = AttributeScope.AUTO


@dataclass(frozen=True, slots=True)
class MetricQueryClause:
    """One metric selection: a name, an aggregation, and optional
    filters / group-by. `name` is the alias a formula refers to (e.g. "a").
    """

    name: str
    metric_name: str
    aggregation: MetricAggregation
    filters: tuple[MetricFilter, ...] = ()
    group_by: tuple[MetricGroupBy, ...] = ()
    # Required for QUANTILE / HISTOGRAM_QUANTILE; ignored otherwise.
    quantile: float | None = None

    def __post_init__(self) -> None:
        if self.aggregation.needs_quantile:
            if self.quantile is None:
                raise ValueError(f"{self.aggregation} requires a quantile")
            if not 0.0 < self.quantile < 1.0:
                raise ValueError("quantile must be in (0, 1)")
        if not self.name:
            raise ValueError("clause name must be non-empty")


@dataclass(frozen=True, slots=True)
class MetricQueryRequest:
    """A whole metric query: one or more clauses over a shared time grid,
    with an optional formula combining them by clause name.

    `interval` is on the request (not per clause) so every series in the
    response shares one bucket grid — required for a formula like "a / b"
    to align, and the right default anyway. None means auto-pick from the
    range.
    """

    clauses: tuple[MetricQueryClause, ...]
    date_from: dt.datetime
    date_to: dt.datetime
    interval: str | None = None
    formula: str | None = None

    def __post_init__(self) -> None:
        if not self.clauses:
            raise ValueError("at least one clause is required")
        if len(self.clauses) > MAX_CLAUSES_PER_QUERY:
            raise ValueError(f"at most {MAX_CLAUSES_PER_QUERY} clauses are allowed per query")
        if self.date_to <= self.date_from:
            raise ValueError("date_to must be after date_from")
        names = [c.name for c in self.clauses]
        if len(names) != len(set(names)):
            raise ValueError("clause names must be unique")


@dataclass(frozen=True, slots=True)
class MetricPoint:
    """One bucketed datapoint. `time` is the bucket start, ISO 8601.
    `value` is None when the bucket's aggregate isn't representable (e.g.
    a float overflow to inf) — consumers render a gap."""

    time: str
    value: float | None


@dataclass(frozen=True, slots=True)
class MetricSeries:
    """One line on a chart: the label values that identify it plus its
    points. `labels` is empty for an ungrouped query. `clause` records
    which clause produced it (the formula result uses `clause="formula"`).
    """

    labels: dict[str, str]
    points: tuple[MetricPoint, ...]
    metric_name: str | None = None
    clause: str | None = None


@dataclass(frozen=True, slots=True)
class MetricAnomalyDimension:
    """One label value's behavior across the baseline/anomaly windows."""

    key: str
    label: str
    baseline_value: float
    anomaly_value: float
    # anomaly_value / baseline_value; 0.0 baselines yield the anomaly value
    # itself (treat as "new" traffic).
    change_ratio: float


@dataclass(frozen=True, slots=True)
class MetricAnomalyReport:
    """Everything an investigator needs to characterize 'metric X looks
    wrong': how the anomaly window compares to the baseline, when it
    started, and which label values moved the most."""

    metric_name: str
    aggregation: str
    interval: str
    baseline_from: str
    baseline_to: str
    anomaly_from: str
    anomaly_to: str
    baseline_mean: float
    baseline_stddev: float
    anomaly_mean: float
    anomaly_peak: float
    # anomaly_mean / baseline_mean; 0.0 baselines yield anomaly_mean.
    change_ratio: float
    direction: str  # "up" | "down" | "flat"
    onset_time: str | None
    top_movers: tuple[MetricAnomalyDimension, ...]
    series: MetricSeries


@dataclass(frozen=True, slots=True)
class MetricEventSample:
    """A single raw metric emission: one `metric_samples` row enriched with its
    `metric_series` labels. Backs the Samples view and the metric->trace pivot.
    Distinct from `MetricSeries`, which is aggregated at query time.
    """

    timestamp: str  # ISO 8601
    metric_name: str
    metric_type: str  # OTel type: gauge | sum | histogram | summary | exponential_histogram
    value: float
    unit: str
    service_name: str
    trace_id: str
    span_id: str
    attributes: dict[str, str]
    resource_attributes: dict[str, str]


@dataclass(frozen=True, slots=True)
class CompanionMetric:
    """A metric to check alongside the primary one to confirm or rule out a
    cause. `role` is a short hint ('traffic', 'saturation', 'processing') shown
    in the narrative. `aggregation`/`quantile` default by the metric's OTel type.
    """

    metric_name: str
    role: str
    aggregation: str | None = None
    quantile: float | None = None


@dataclass(frozen=True, slots=True)
class CompanionVerdict:
    """How a companion metric behaved over the same window as the symptom — the
    basis for 'it wasn't a traffic surge' / 'processing kept up' reasoning.
    """

    metric_name: str
    role: str
    aggregation: str
    direction: str  # "up" | "down" | "flat"
    change_ratio: float
    # True when the companion moved materially in the symptom window (so it
    # plausibly relates to the cause); False rules it out.
    moved_with_symptom: bool
    # Quantile the companion was aggregated at (histogram_quantile only); carried
    # so a re-runnable chart spec can reproduce the same aggregation.
    quantile: float | None = None


@dataclass(frozen=True, slots=True)
class InvestigationChartSpec:
    """A metric query plus the frozen window to render it over. Re-runnable —
    the report re-runs the same query over the same window for live data —
    never baked, the opposite of snapshotting datapoints into constants.
    """

    title: str
    metric_name: str
    aggregation: str
    anomaly_from: str  # ISO 8601
    anomaly_to: str
    filters: tuple[MetricFilter, ...] = ()
    quantile: float | None = None


@dataclass(frozen=True, slots=True)
class TraceExemplar:
    """A pointer from a metric sample into a concrete trace at the anomaly, for
    the metric->trace pivot. Populated by the trace-pivot primitive once the
    `metric_samples` table is live; empty until then.
    """

    trace_id: str
    span_id: str
    timestamp: str  # ISO 8601
    value: float


@dataclass(frozen=True, slots=True)
class InvestigationEvidence:
    """Cross-signal pointers gathered around onset: trace exemplars to pivot
    into, and a ready-to-run log filter for the implicated service/window.
    `log_filter` is None when no service could be implicated.
    """

    service_name: str | None
    trace_exemplars: tuple[TraceExemplar, ...] = ()
    log_filter: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class InvestigationResult:
    """The structured outcome of investigating a metric symptom. Produced once
    by `investigate()` and consumed three ways: the agent narrates it, the
    in-app explorer renders it interactively, and the incident report
    serializes it. This shared shape is the seam between investigate and
    display.
    """

    metric_name: str
    symptom: MetricAnomalyReport
    blast_radius: str  # "localized" | "shared" | "unknown"
    companions: tuple[CompanionVerdict, ...]
    chart_specs: tuple[InvestigationChartSpec, ...]
    evidence: InvestigationEvidence
    confidence: str  # "high" | "medium" | "low"
    narrative: str


@dataclass(frozen=True, slots=True)
class IncidentContext:
    """Structured context from a fired alert (or a manual "this looks wrong"),
    so an investigation never has to parse a timestamp out of prose. `fired_at`
    is an explicit UTC instant; the anomaly window is derived as
    [fired_at - lookback, fired_at + leadout], and `service_name` scopes the
    investigation to the implicated service.
    """

    metric_name: str
    fired_at: dt.datetime
    lookback: dt.timedelta = dt.timedelta(minutes=15)
    leadout: dt.timedelta = dt.timedelta(minutes=15)
    service_name: str | None = None
    companions: tuple[CompanionMetric, ...] = ()

    def __post_init__(self) -> None:
        # The docstring promises a UTC instant; a naive datetime would be taken
        # as UTC by the window math and silently mis-bucket a local-time fire.
        # Fail fast at construction so callers stay explicit.
        if self.fired_at.tzinfo is None:
            raise ValueError("fired_at must be timezone-aware (UTC)")
