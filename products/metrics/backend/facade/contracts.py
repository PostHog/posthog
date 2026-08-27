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

from .enums import AttributeScope, FilterOp, HealthState, MetricAggregation, MetricType

# Each clause runs its own ClickHouse query on the shared logs cluster, so
# the clause count per request is hard-capped.
MAX_CLAUSES_PER_QUERY = 10

# Private-alpha gate. Every read surface (viewset, query runner, MCP tools)
# must check the same flag, or one of them becomes a bypass.
METRICS_FEATURE_FLAG = "metrics"

# Gates the pipelines surface (topology CRUD + evaluation) independently of
# the base metrics viewer, so it can roll out on its own schedule.
PIPELINES_FEATURE_FLAG = "metrics-pipelines"

# Caps enforced by `parse_pipeline_config`, mirrored in the serializer so the
# two can't drift.
MAX_PIPELINE_NODES = 20
MAX_PIPELINE_STATS_PER_NODE = 12
MAX_PIPELINE_EDGES = 40
MAX_PIPELINE_BREAKDOWN_TOP_N = 20

# The per-item caps above multiply out to far more ClickHouse queries than one
# evaluation should ever issue, so the total is capped directly. A stat costs
# one query, a breakdown adds another, and an edge costs two (current window
# plus baseline). The evaluate endpoint's throttles only bind personal API key
# traffic, so this is what bounds a session-authenticated caller.
MAX_PIPELINE_EVALUATION_QUERIES = 120


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
    # Constrains rows to one metric type; None keeps all types (legacy).
    metric_type: MetricType | None = None

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
    # Charts want a gap-free line, so a bucket a series did not report is
    # filled with 0.0 by default. Set False when the caller has to tell
    # "reported zero" apart from "did not report" — a series that stopped
    # mid-window would otherwise read as currently sitting at zero.
    zero_fill: bool = True

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
class PipelineThresholdBounds:
    """Inclusive healthy range for one severity: a value breaches when it is
    below `lower` or above `upper`. Either side may be open (None)."""

    lower: float | None = None
    upper: float | None = None


@dataclass(frozen=True, slots=True)
class PipelineStatThresholds:
    """Warn/crit bounds for a stat. A missing severity never fires."""

    warn: PipelineThresholdBounds | None = None
    crit: PipelineThresholdBounds | None = None


@dataclass(frozen=True, slots=True)
class PipelineBreakdownConfig:
    """Optional per-label breakdown table under a stat (e.g. lag by
    partition). Rows beyond `top_n` are rolled into one "others" row."""

    group_by_key: str
    top_n: int = 10
    scope: AttributeScope = AttributeScope.AUTO


@dataclass(frozen=True, slots=True)
class PipelineLink:
    """External deep link rendered on a node's drill panel."""

    label: str
    url: str


@dataclass(frozen=True, slots=True)
class PipelineStatConfig:
    """One health stat on a node: a metric selection plus thresholds.
    `format` is a display hint only (rate|bytes|pct|count|duration)."""

    id: str
    label: str
    format: str
    metric_name: str
    aggregation: MetricAggregation
    filters: tuple[MetricFilter, ...] = ()
    quantile: float | None = None
    metric_type: MetricType | None = None
    thresholds: PipelineStatThresholds | None = None
    breakdown: PipelineBreakdownConfig | None = None


@dataclass(frozen=True, slots=True)
class PipelineNodeConfig:
    """One component in the topology. `headline_stat_ids` picks the rows
    shown on the collapsed node card (all stats show in the drill panel)."""

    id: str
    name: str
    kind: str
    stats: tuple[PipelineStatConfig, ...]
    headline_stat_ids: tuple[str, ...] = ()
    links: tuple[PipelineLink, ...] = ()
    note: str = ""


@dataclass(frozen=True, slots=True)
class PipelineEdgeConfig:
    """A directed flow between two nodes, measured by one metric. The edge is
    "hot" when current throughput reaches `hot_multiplier` x the same-length
    window `baseline_offset` ago."""

    source: str
    target: str
    metric_name: str
    aggregation: MetricAggregation
    filters: tuple[MetricFilter, ...] = ()
    quantile: float | None = None
    metric_type: MetricType | None = None
    baseline_offset: str = "-7d"
    hot_multiplier: float = 2.0


@dataclass(frozen=True, slots=True)
class PipelineVariableConfig:
    """A pipeline-level selector (e.g. environment) that injects one label
    filter into every stat and edge query when a value is chosen."""

    key: str
    label: str
    filter_key: str
    options: tuple[str, ...] = ()
    default: str | None = None


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    """A whole validated topology. Always obtained via
    `parse_pipeline_config` — construction from raw JSON is where duplicate
    ids, dangling edges, and cycles are rejected."""

    nodes: tuple[PipelineNodeConfig, ...]
    edges: tuple[PipelineEdgeConfig, ...]
    variables: tuple[PipelineVariableConfig, ...] = ()


class PipelineNotFoundError(Exception):
    """Raised when a pipeline id does not exist for the team (or is deleted)."""


@dataclass(frozen=True, slots=True)
class PipelineActor:
    """Minimal user identity attached to a pipeline record."""

    id: int
    email: str
    first_name: str


@dataclass(frozen=True, slots=True)
class MetricsPipelineRecord:
    """A stored pipeline as the API serves it. `config` is the raw validated
    JSON object (the wire shape), not the parsed `PipelineConfig` — clients
    round-trip it through the editor."""

    id: str
    name: str
    description: str
    config: dict
    enabled: bool
    created_at: str
    created_by: PipelineActor | None
    updated_at: str | None


@dataclass(frozen=True, slots=True)
class PipelineBreakdownRow:
    """One row of a stat's breakdown table."""

    label: str
    value: float


@dataclass(frozen=True, slots=True)
class PipelineStatResult:
    """A stat's evaluated value and verdict. `value` is None exactly when
    `state` is NO_DATA."""

    id: str
    label: str
    format: str
    value: float | None
    state: HealthState
    breakdown_rows: tuple[PipelineBreakdownRow, ...] = ()
    breakdown_others: PipelineBreakdownRow | None = None


@dataclass(frozen=True, slots=True)
class PipelineNodeResult:
    """A node's rolled-up verdict: the worst reporting stat wins; a node
    with only silent stats is NO_DATA."""

    id: str
    state: HealthState
    stats: tuple[PipelineStatResult, ...]


@dataclass(frozen=True, slots=True)
class PipelineEdgeResult:
    """An edge's throughput vs its baseline. `multiplier` is None when the
    baseline window had no signal (new traffic has no meaningful ratio).
    `points` is the current-window series for the sparkline."""

    source: str
    target: str
    current_value: float | None
    baseline_value: float | None
    multiplier: float | None
    hot: bool
    points: tuple[MetricPoint, ...]


@dataclass(frozen=True, slots=True)
class PipelineAlert:
    """One alert-strip entry, derived server-side from a breached stat."""

    severity: str  # "warning" | "critical"
    node_id: str
    stat_id: str
    message: str


@dataclass(frozen=True, slots=True)
class PipelineEvaluation:
    """One refresh tick of a whole pipeline: every node and edge verdict plus
    the derived alert strip, over one explicit window."""

    nodes: tuple[PipelineNodeResult, ...]
    edges: tuple[PipelineEdgeResult, ...]
    alerts: tuple[PipelineAlert, ...]
    date_from: str
    date_to: str


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
    # Observations behind this point: 1 for gauges/counters, the distribution
    # count for histograms/summaries (value is then the sum; avg = value/count).
    count: int
    unit: str
    aggregation_temporality: str  # "delta" | "cumulative" | "" (gauges)
    is_monotonic: bool
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
    the metric->trace pivot. Trace/span ids are hex, matching the tracing
    product's contract, so they can be passed straight to a trace URL.
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
    must be timezone-aware and is normalized to UTC at construction; the
    anomaly window is derived as [fired_at - lookback, fired_at + leadout],
    and `service_name` scopes the investigation to the implicated service.
    """

    metric_name: str
    fired_at: dt.datetime
    lookback: dt.timedelta = dt.timedelta(minutes=15)
    leadout: dt.timedelta = dt.timedelta(minutes=15)
    service_name: str | None = None
    companions: tuple[CompanionMetric, ...] = ()

    def __post_init__(self) -> None:
        # A naive datetime would be taken as UTC by the window math and
        # silently mis-bucket a local-time fire; fail fast at construction.
        # Aware non-UTC instants are fine — normalize them so downstream
        # window math always operates on UTC.
        if self.fired_at.tzinfo is None:
            raise ValueError("fired_at must be timezone-aware")
        object.__setattr__(self, "fired_at", self.fired_at.astimezone(dt.UTC))


@dataclass(frozen=True, slots=True)
class MetricsServiceOverview:
    """One service's ingestion rollup inside the overview window."""

    service_name: str
    metric_names: int
    series: int
    last_seen: str  # ISO 8601


@dataclass(frozen=True, slots=True)
class MetricsOverview:
    """The landing-page answer to "is anything ingesting": how fresh the
    newest datapoint is, plus window-scoped inventory counts per service.

    `last_seen` deliberately ignores the window — when ingestion stops, the
    window-scoped numbers go to zero but the status strip still needs to say
    how long ago the last datapoint arrived. None means never ingested (or
    everything aged past the series table's retention).
    """

    last_seen: str | None  # ISO 8601
    metric_names: int
    series: int
    lookback_seconds: int
    services: tuple[MetricsServiceOverview, ...]


@dataclass(frozen=True, slots=True)
class MetricSampleView:
    """One raw reading, as it sits in storage before any reduction."""

    time: str
    value: float


@dataclass(frozen=True, slots=True)
class MetricSeriesBreakdown:
    """One physical series inside a bucket, and the value it contributed.

    `samples` is trimmed for display; `sample_count` always reports how many
    the series really sent, so a trimmed list can't be mistaken for a quiet one.
    """

    service_name: str
    labels: dict[str, str]
    resource_labels: dict[str, str]
    samples: tuple[MetricSampleView, ...]
    sample_count: int
    samples_truncated: bool
    # None when the aggregation has no per-series step, as percentiles do not:
    # they read the pooled readings, so no single number is this series'
    # contribution.
    value: float | None


@dataclass(frozen=True, slots=True)
class MetricBucketDecomposition:
    """One chart point taken apart into the series and samples behind it.

    `reference_value` is recomputed from the raw samples independently of the
    query builders; `actual_value` is what the product would plot. `agrees`
    compares them, and is the part worth reading first — a mismatch means one
    of the two reductions is wrong, and the breakdown shows where they parted.
    """

    metric_name: str
    metric_type: str
    temporality: str
    aggregation: str
    bucket_start: str
    interval: str
    temporal_reducer: str
    spatial_reducer: str
    series: tuple[MetricSeriesBreakdown, ...]
    series_count: int
    sample_count: int
    series_truncated: bool
    rows_truncated: bool
    reference_value: float | None
    actual_value: float | None
    # None when the raw read was truncated: the reference then covers only part
    # of the bucket, so comparing it to the chart proves nothing either way.
    agrees: bool | None
