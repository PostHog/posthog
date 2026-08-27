/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface AppMetricSeriesApi {
    name: string
    values: number[]
}

export interface AppMetricsResponseApi {
    labels: string[]
    series: AppMetricSeriesApi[]
}

export type AppMetricsTotalsResponseApiTotals = { [key: string]: number }

export interface AppMetricsTotalsResponseApi {
    totals: AppMetricsTotalsResponseApiTotals
}

export interface _MetricAttributeValueApi {
    /** The attribute value (same as name; kept for picker compatibility). */
    id: string
    /** The attribute value. */
    name: string
    /** Number of data points observed with this value in the window. */
    count: number
}

export interface _MetricAttributeValuesResponseApi {
    /** Observed values for the requested key, most frequent first. */
    results: _MetricAttributeValueApi[]
}

export interface _MetricAttributeKeyApi {
    /** Attribute key as it appears on the team's metrics (e.g. 'env', 'k8s.pod.name'). */
    name: string
}

export interface _MetricAttributeKeysResponseApi {
    /** Distinct attribute keys (datapoint and resource attributes merged), most frequent first. */
    results: _MetricAttributeKeyApi[]
    /** Number of keys returned. */
    count: number
}

/**
 * * `sum` - sum
 * * `avg` - avg
 * * `count` - count
 * * `p95` - p95
 * * `rate` - rate
 * * `increase` - increase
 * * `histogram_quantile` - histogram_quantile
 */
export type AggregationEnumApi = (typeof AggregationEnumApi)[keyof typeof AggregationEnumApi]

export const AggregationEnumApi = {
    Sum: 'sum',
    Avg: 'avg',
    Count: 'count',
    P95: 'p95',
    Rate: 'rate',
    Increase: 'increase',
    HistogramQuantile: 'histogram_quantile',
} as const

/**
 * * `eq` - eq
 * * `neq` - neq
 * * `regex` - regex
 * * `not_regex` - not_regex
 */
export type OpEnumApi = (typeof OpEnumApi)[keyof typeof OpEnumApi]

export const OpEnumApi = {
    Eq: 'eq',
    Neq: 'neq',
    Regex: 'regex',
    NotRegex: 'not_regex',
} as const

/**
 * * `resource` - resource
 * * `attribute` - attribute
 * * `auto` - auto
 */
export type MetricAttributeScopeEnumApi = (typeof MetricAttributeScopeEnumApi)[keyof typeof MetricAttributeScopeEnumApi]

export const MetricAttributeScopeEnumApi = {
    Resource: 'resource',
    Attribute: 'attribute',
    Auto: 'auto',
} as const

export interface _MetricFilterApi {
    /**
     * Attribute name to filter on, without any type-tag suffix (e.g. 'k8s.pod.name', 'env').
     * @maxLength 255
     */
    key: string
    /** Comparison operator. 'regex'/'not_regex' use RE2 syntax. Negative operators also match rows that lack the key entirely, mirroring Prometheus negative matchers.
     *
     * * `eq` - eq
     * * `neq` - neq
     * * `regex` - regex
     * * `not_regex` - not_regex */
    op?: OpEnumApi
    /**
     * Value to compare against. For regex operators this is the pattern.
     * @maxLength 1024
     */
    value: string
    /** Where the attribute lives: 'resource' = per-target resource attributes (k8s.pod.name, service.version), 'attribute' = per-datapoint attributes (http.method, path), 'auto' = resource first with per-datapoint fallback. Use 'auto' unless you know the exact scope.
     *
     * * `resource` - resource
     * * `attribute` - attribute
     * * `auto` - auto */
    scope?: MetricAttributeScopeEnumApi
}

export interface _MetricAnomalyBodyApi {
    /**
     * Exact metric name to characterize (e.g. 'metrics_rate_limiter_message_lag_seconds').
     * @maxLength 255
     */
    metricName: string
    /** Start of the suspicious window (inclusive). ISO 8601 — e.g. when the alert fired or the graph started looking wrong. */
    anomalyFrom: string
    /** End of the suspicious window (exclusive). Defaults to now. */
    anomalyTo?: string
    /** Start of the healthy comparison window. Defaults to one anomaly-window-length before baselineTo. */
    baselineFrom?: string
    /** End of the healthy comparison window. Defaults to anomalyFrom. Must not extend past anomalyFrom. */
    baselineTo?: string
    /** Aggregation to characterize. Omit to auto-pick from the metric's OTel type (counter -> rate, gauge -> avg, histogram -> histogram_quantile 0.95).
     *
     * * `sum` - sum
     * * `avg` - avg
     * * `count` - count
     * * `p95` - p95
     * * `rate` - rate
     * * `increase` - increase
     * * `histogram_quantile` - histogram_quantile */
    aggregation?: AggregationEnumApi | null
    /**
     * Quantile for histogram_quantile. Defaults to 0.95.
     * @minimum 0
     * @maximum 1
     * @nullable
     */
    quantile?: number | null
    /** Label predicates narrowing which series are characterized. */
    filters?: _MetricFilterApi[]
    /**
     * Label keys to drill into when finding which label values moved. Omit to auto-discover the most common keys on this metric (plus service_name). Max 4 are used.
     * @items.maxLength 255
     */
    candidateKeys?: string[]
}

export interface _MetricAnomalyRequestApi {
    /** The anomaly characterization to run. */
    query: _MetricAnomalyBodyApi
}

/**
 * * `up` - up
 * * `down` - down
 * * `flat` - flat
 */
export type MetricAnomalyDirectionEnumApi =
    (typeof MetricAnomalyDirectionEnumApi)[keyof typeof MetricAnomalyDirectionEnumApi]

export const MetricAnomalyDirectionEnumApi = {
    Up: 'up',
    Down: 'down',
    Flat: 'flat',
} as const

export interface _MetricAnomalyDimensionApi {
    /** Label key that was drilled into. */
    key: string
    /** Label value this row describes. */
    label: string
    /** Mean value over the baseline window for this label value. */
    baseline_value: number
    /** Mean value over the anomaly window for this label value. */
    anomaly_value: number
    /** anomaly_value / baseline_value. A zero baseline yields the anomaly value itself (new traffic). */
    change_ratio: number
}

export interface _MetricQueryPointApi {
    /** Bucket start as ISO 8601 timestamp. */
    time: string
    /**
     * Aggregated value for the bucket. Null when the aggregate isn't representable (e.g. float overflow) — render as a gap.
     * @nullable
     */
    value: number | null
}

/**
 * Label values identifying this series. Empty for an ungrouped query.
 */
export type _MetricSeriesApiLabels = { [key: string]: string }

export interface _MetricSeriesApi {
    /** Label values identifying this series. Empty for an ungrouped query. */
    labels: _MetricSeriesApiLabels
    /** Time-bucketed points, ordered by time ascending. */
    points: _MetricQueryPointApi[]
    /**
     * Metric the series was computed from. Null for formula results.
     * @nullable
     */
    metric_name?: string | null
    /**
     * Name of the query clause that produced this series.
     * @nullable
     */
    clause?: string | null
}

export interface _MetricAnomalyReportApi {
    /** Metric that was characterized. */
    metric_name: string
    /** Aggregation used (auto-picked when not specified). */
    aggregation: string
    /** Bucket size of the analysis grid. */
    interval: string
    /** Baseline window start, ISO 8601. */
    baseline_from: string
    /** Baseline window end, ISO 8601. */
    baseline_to: string
    /** Anomaly window start, ISO 8601. */
    anomaly_from: string
    /** Anomaly window end, ISO 8601. */
    anomaly_to: string
    /** Mean over the baseline window. */
    baseline_mean: number
    /** Population stddev over the baseline window. */
    baseline_stddev: number
    /** Mean over the anomaly window. */
    anomaly_mean: number
    /** Maximum bucket value in the anomaly window. */
    anomaly_peak: number
    /** anomaly_mean / baseline_mean. A zero baseline yields anomaly_mean itself. */
    change_ratio: number
    /** Which way the metric moved versus the baseline.
     *
     * * `up` - up
     * * `down` - down
     * * `flat` - flat */
    direction: MetricAnomalyDirectionEnumApi
    /**
     * First bucket clearly outside the baseline range (3 stddevs or 50% relative change), or null if no clear onset.
     * @nullable
     */
    onset_time: string | null
    /** Label values whose behavior changed the most between windows, largest change first. Empty when nothing moved or the metric has no labels. */
    top_movers: _MetricAnomalyDimensionApi[]
    /** The metric across baseline + anomaly windows on one grid, for plotting or further inspection. */
    series: _MetricSeriesApi
}

/**
 * * `gauge` - gauge
 * * `sum` - sum
 * * `histogram` - histogram
 * * `exponential_histogram` - exponential_histogram
 * * `summary` - summary
 */
export type OtelMetricTypeEnumApi = (typeof OtelMetricTypeEnumApi)[keyof typeof OtelMetricTypeEnumApi]

export const OtelMetricTypeEnumApi = {
    Gauge: 'gauge',
    Sum: 'sum',
    Histogram: 'histogram',
    ExponentialHistogram: 'exponential_histogram',
    Summary: 'summary',
} as const

/**
 * * `second` - second
 * * `minute` - minute
 * * `minute_5` - minute_5
 * * `minute_15` - minute_15
 * * `hour` - hour
 * * `hour_6` - hour_6
 * * `day` - day
 * * `week` - week
 */
export type MetricQueryIntervalEnumApi = (typeof MetricQueryIntervalEnumApi)[keyof typeof MetricQueryIntervalEnumApi]

export const MetricQueryIntervalEnumApi = {
    Second: 'second',
    Minute: 'minute',
    Minute5: 'minute_5',
    Minute15: 'minute_15',
    Hour: 'hour',
    Hour6: 'hour_6',
    Day: 'day',
    Week: 'week',
} as const

export interface _MetricExplainBodyApi {
    /**
     * Exact metric name whose bucket should be taken apart.
     * @maxLength 255
     */
    metricName: string
    /** Constrain the bucket to one metric type. A name can exist as several types; without this, rows of every type sharing the name are decomposed together.
     *
     * * `gauge` - gauge
     * * `sum` - sum
     * * `histogram` - histogram
     * * `exponential_histogram` - exponential_histogram
     * * `summary` - summary */
    metricType?: OtelMetricTypeEnumApi | null
    /** The aggregation whose result should be explained. 'histogram_quantile' is rejected: it reduces bucket-count arrays rather than scalar samples, so there is no per-series value to lay out.
     *
     * * `sum` - sum
     * * `avg` - avg
     * * `count` - count
     * * `p95` - p95
     * * `rate` - rate
     * * `increase` - increase
     * * `histogram_quantile` - histogram_quantile */
    aggregation?: AggregationEnumApi
    /**
     * Quantile in (0, 1) applied across series. Defaults to 0.95 for the 'p95' aggregation.
     * @minimum 0
     * @maximum 1
     * @nullable
     */
    quantile?: number | null
    /** Label predicates ANDed together, matching the chart the point came from. */
    filters?: _MetricFilterApi[]
    /** Start of the bucket to explain, as returned in a query result's 'time'. ISO 8601. */
    bucketStart: string
    /** Bucket size the point was plotted at. Must match the query that produced it, or the decomposition explains a different span.
     *
     * * `second` - second
     * * `minute` - minute
     * * `minute_5` - minute_5
     * * `minute_15` - minute_15
     * * `hour` - hour
     * * `hour_6` - hour_6
     * * `day` - day
     * * `week` - week */
    interval: MetricQueryIntervalEnumApi
}

export interface _MetricExplainRequestApi {
    /** The chart point to take apart. */
    query: _MetricExplainBodyApi
}

/**
 * * `none` - none
 * * `last` - last
 * * `avg_over_time` - avg_over_time
 * * `sum_over_time` - sum_over_time
 * * `increase` - increase
 * * `pooled_samples` - pooled_samples
 */
export type TemporalReducerEnumApi = (typeof TemporalReducerEnumApi)[keyof typeof TemporalReducerEnumApi]

export const TemporalReducerEnumApi = {
    None: 'none',
    Last: 'last',
    AvgOverTime: 'avg_over_time',
    SumOverTime: 'sum_over_time',
    Increase: 'increase',
    PooledSamples: 'pooled_samples',
} as const

/**
 * * `sum` - sum
 * * `avg` - avg
 * * `min` - min
 * * `max` - max
 * * `quantile` - quantile
 * * `count_series` - count_series
 */
export type SpatialReducerEnumApi = (typeof SpatialReducerEnumApi)[keyof typeof SpatialReducerEnumApi]

export const SpatialReducerEnumApi = {
    Sum: 'sum',
    Avg: 'avg',
    Min: 'min',
    Max: 'max',
    Quantile: 'quantile',
    CountSeries: 'count_series',
} as const

export interface _MetricSampleViewApi {
    /** Sample timestamp, ISO 8601. */
    time: string
    /** Raw stored reading, before any reduction. */
    value: number
}

/**
 * Per-data-point attributes identifying the series.
 */
export type _MetricSeriesBreakdownApiLabels = { [key: string]: string }

/**
 * Resource attributes identifying the scrape target.
 */
export type _MetricSeriesBreakdownApiResourceLabels = { [key: string]: string }

export interface _MetricSeriesBreakdownApi {
    /** Service that reported this series. */
    service_name: string
    /** Per-data-point attributes identifying the series. */
    labels: _MetricSeriesBreakdownApiLabels
    /** Resource attributes identifying the scrape target. */
    resource_labels: _MetricSeriesBreakdownApiResourceLabels
    /** The series' raw samples in this bucket, oldest first, trimmed for display. */
    samples: _MetricSampleViewApi[]
    /** How many samples the series actually sent, even when 'samples' was trimmed. */
    sample_count: number
    /** Whether 'samples' lists fewer samples than arrived. */
    samples_truncated: boolean
    /**
     * What this series contributed after the per-series reduction. Null for percentiles, which read the pooled readings and so have no single per-series contribution.
     * @nullable
     */
    value: number | null
}

export interface _MetricBucketDecompositionApi {
    /** Metric that was decomposed. */
    metric_name: string
    /** OTel metric type observed in the bucket. */
    metric_type: string
    /** OTel aggregation temporality observed in the bucket ('cumulative', 'delta', or empty for gauges). */
    temporality: string
    /** Aggregation that was explained. */
    aggregation: string
    /** Start of the explained bucket, ISO 8601. */
    bucket_start: string
    /** Bucket size the point was plotted at. */
    interval: string
    /** How each series' samples were collapsed to one value: 'last' for an instant gauge reading, 'avg_over_time' for an average, 'sum_over_time' for delta counters, 'increase' for cumulative counters, and 'pooled_samples' for percentiles, which skip the per-series step entirely.
     *
     * * `none` - none
     * * `last` - last
     * * `avg_over_time` - avg_over_time
     * * `sum_over_time` - sum_over_time
     * * `increase` - increase
     * * `pooled_samples` - pooled_samples */
    temporal_reducer: TemporalReducerEnumApi
    /** How the per-series values were combined into the bucket's number.
     *
     * * `sum` - sum
     * * `avg` - avg
     * * `min` - min
     * * `max` - max
     * * `quantile` - quantile
     * * `count_series` - count_series */
    spatial_reducer: SpatialReducerEnumApi
    /** The series behind the point, largest contributors first, trimmed for display. */
    series: _MetricSeriesBreakdownApi[]
    /** How many series reported in the bucket. */
    series_count: number
    /** How many raw samples the bucket held across all series. */
    sample_count: number
    /** Whether 'series' lists fewer series than reported. */
    series_truncated: boolean
    /** Whether the bucket held more raw rows than the decomposition reads. Totals are computed only over the rows that were read. */
    rows_truncated: boolean
    /**
     * The bucket's value recomputed from the raw samples, independently of the query builders. Null when no series reported.
     * @nullable
     */
    reference_value: number | null
    /**
     * The value the product would plot for this point. Null when the query returned no row.
     * @nullable
     */
    actual_value: number | null
    /**
     * Whether the two values match. False means one of the reductions is wrong, and the series breakdown shows where they parted. Null when the raw read was truncated, so the two are not comparable.
     * @nullable
     */
    agrees: boolean | null
}

export interface _MetricExplainResponseApi {
    /** The bucket taken apart. */
    decomposition: _MetricBucketDecompositionApi
}

export interface _HasMetricsResponseApi {
    /** Whether the team has ingested any metrics. */
    hasMetrics: boolean
}

export interface _MetricsOverviewServiceApi {
    /** Service that reported metrics inside the window. */
    service_name: string
    /** Distinct metric names this service reported in the window. */
    metric_names: number
    /** Distinct series (metric + label-set combinations) this service reported in the window. */
    series: number
    /** When this service's newest datapoint arrived, ISO 8601. */
    last_seen: string
}

export interface _MetricsOverviewResponseApi {
    /**
     * When the newest datapoint arrived across all series, ISO 8601. Unlike the counts this ignores the window, so it still answers 'when did ingestion stop'. Null when nothing was ever ingested.
     * @nullable
     */
    last_seen: string | null
    /** Distinct metric names reported inside the window. */
    metric_names: number
    /** Distinct series (metric + label-set combinations) reported inside the window. */
    series: number
    /** Length of the rollup window in seconds, so consumers can label the counts. */
    lookback_seconds: number
    /** Per-service rollup for the window, largest series count first. Capped at the 500 largest. */
    services: _MetricsOverviewServiceApi[]
}

export interface _MetricGroupByApi {
    /**
     * Attribute name to split series by (e.g. 'k8s.pod.name', 'env').
     * @maxLength 255
     */
    key: string
    /** Where the attribute lives; same semantics as filter scope. Use 'auto' unless you know the exact scope.
     *
     * * `resource` - resource
     * * `attribute` - attribute
     * * `auto` - auto */
    scope?: MetricAttributeScopeEnumApi
}

export interface _MetricClauseApi {
    /**
     * Clause name a formula refers to (e.g. 'a').
     * @maxLength 64
     */
    name: string
    /**
     * Exact metric name this clause queries.
     * @maxLength 255
     */
    metricName: string
    /** Constrain the query to one metric type. A name can exist as several types (e.g. a counter and a gauge); without this, rows of every type sharing the name are blended into one aggregate. Get the type from 'metric-names-list'.
     *
     * * `gauge` - gauge
     * * `sum` - sum
     * * `histogram` - histogram
     * * `exponential_histogram` - exponential_histogram
     * * `summary` - summary */
    metricType?: OtelMetricTypeEnumApi | null
    /** Aggregation applied per time bucket; same semantics as the top-level aggregation.
     *
     * * `sum` - sum
     * * `avg` - avg
     * * `count` - count
     * * `p95` - p95
     * * `rate` - rate
     * * `increase` - increase
     * * `histogram_quantile` - histogram_quantile */
    aggregation?: AggregationEnumApi
    /**
     * Quantile in (0, 1) for 'histogram_quantile'.
     * @minimum 0
     * @maximum 1
     * @nullable
     */
    quantile?: number | null
    /** Label predicates ANDed together for this clause. */
    filters?: _MetricFilterApi[]
    /** Labels to split this clause into separate series by. */
    groupBy?: _MetricGroupByApi[]
}

export interface _MetricQueryBodyApi {
    /**
     * Exact metric name to query (e.g. 'http.server.duration'). Single-clause shorthand — mutually exclusive with 'clauses'.
     * @maxLength 255
     */
    metricName?: string
    /** Constrain the query to one metric type. A name can exist as several types (e.g. a counter and a gauge); without this, rows of every type sharing the name are blended into one aggregate. Get the type from 'metric-names-list'.
     *
     * * `gauge` - gauge
     * * `sum` - sum
     * * `histogram` - histogram
     * * `exponential_histogram` - exponential_histogram
     * * `summary` - summary */
    metricType?: OtelMetricTypeEnumApi | null
    /** Aggregation applied per time bucket, always across series rather than across raw samples. 'sum', 'avg' and 'p95' reduce each series to its last sample in the bucket and then combine those, so the result does not scale with the scrape rate; 'count' is the number of series that reported. 'rate' (per-second) and 'increase' are counter-aware: per-series deltas with Prometheus counter-reset handling, temporality-aware (delta-temporality samples count as-is). 'histogram_quantile' interpolates from OTel histogram buckets and requires 'quantile'.
     *
     * * `sum` - sum
     * * `avg` - avg
     * * `count` - count
     * * `p95` - p95
     * * `rate` - rate
     * * `increase` - increase
     * * `histogram_quantile` - histogram_quantile */
    aggregation?: AggregationEnumApi
    /**
     * Quantile in (0, 1) for 'histogram_quantile' (e.g. 0.95). Ignored for other aggregations.
     * @minimum 0
     * @maximum 1
     * @nullable
     */
    quantile?: number | null
    /** Label predicates ANDed together. Rows must satisfy every filter. */
    filters?: _MetricFilterApi[]
    /** Labels to split the result into separate series by. Series share one time grid and are capped at the 100 largest. */
    groupBy?: _MetricGroupByApi[]
    /** Bucket size for the shared time grid. Omit to auto-pick (~60 buckets across the range).
     *
     * * `second` - second
     * * `minute` - minute
     * * `minute_5` - minute_5
     * * `minute_15` - minute_15
     * * `hour` - hour
     * * `hour_6` - hour_6
     * * `day` - day
     * * `week` - week */
    interval?: MetricQueryIntervalEnumApi | null
    /** Full multi-clause form: each clause is an independent metric selection sharing the request's time grid (maximum 10). Mutually exclusive with 'metricName'. */
    clauses?: _MetricClauseApi[]
    /**
     * Arithmetic over clause names evaluated server-side per grid point, e.g. '(a - b) / a'. Supports + - * / and parentheses; division by zero yields 0. When set, only the formula result series are returned.
     * @maxLength 512
     * @nullable
     */
    formula?: string | null
    /** Lower bound (inclusive) for the query range. ISO 8601. */
    dateFrom: string
    /** Upper bound (exclusive) for the query range. Defaults to now if omitted. */
    dateTo?: string
}

export interface _MetricQueryRequestApi {
    /** The metric query to execute. */
    query: _MetricQueryBodyApi
}

export interface _MetricQueryResponseApi {
    /** One series per (clause, label-set). A single ungrouped query returns exactly one series with empty labels. */
    results: _MetricSeriesApi[]
}

export interface _MetricSamplesBodyApi {
    /**
     * Exact metric name to list raw emissions for (e.g. 'http.server.duration').
     * @maxLength 255
     */
    metricName: string
    /** Lower bound (inclusive) for the sample window. ISO 8601. */
    dateFrom: string
    /** Upper bound (exclusive) for the sample window. Defaults to now if omitted. */
    dateTo?: string
    /**
     * Restrict to emissions on this trace (hex trace id, as the tracing product uses) — the reverse metric->trace pivot. Omit for all traces.
     * @maxLength 255
     */
    traceId?: string
    /** Constrain the emissions to one metric type. A name can exist as several types (e.g. a counter and a gauge); without this, emissions of every type sharing the name are listed together. Pass the same value used for the chart so both describe the same series.
     *
     * * `gauge` - gauge
     * * `sum` - sum
     * * `histogram` - histogram
     * * `exponential_histogram` - exponential_histogram
     * * `summary` - summary */
    metricType?: OtelMetricTypeEnumApi | null
    /** Label predicates ANDed together, matched against each emission's series. Pass the same filters used for the chart so the emissions listed are the ones behind it. */
    filters?: _MetricFilterApi[]
    /**
     * Max emissions to return, newest first. Defaults to 100, capped at 1000.
     * @minimum 1
     * @maximum 1000
     */
    limit?: number
}

export interface _MetricSamplesRequestApi {
    /** The raw-emissions query to execute. */
    query: _MetricSamplesBodyApi
}

/**
 * Per-emission attributes (high-cardinality labels on the data point).
 */
export type _MetricEventSampleApiAttributes = { [key: string]: string }

/**
 * Attributes of the resource (host, pod, service version) that emitted the metric.
 */
export type _MetricEventSampleApiResourceAttributes = { [key: string]: string }

export interface _MetricEventSampleApi {
    /** When the metric was emitted, ISO 8601. */
    timestamp: string
    /** Metric this emission belongs to. */
    metric_name: string
    /** OTel metric type: gauge, sum, histogram, summary, or exponential_histogram. */
    metric_type: string
    /** The emitted value. For histogram/summary points this is the distribution sum; pair with count. */
    value: number
    /** Observations behind this point: 1 for gauges/counters, the distribution count for histograms/summaries. */
    count: number
    /** Unit of the value, if any. */
    unit: string
    /** For counters: 'delta' or 'cumulative' (decides whether rate() must diff). Empty for gauges. */
    aggregation_temporality: string
    /** True for monotonically increasing counters. */
    is_monotonic: boolean
    /** Service that emitted the metric. */
    service_name: string
    /** Trace this emission belongs to (hex, same form the tracing product uses); empty if none. Use it to pivot to the trace. */
    trace_id: string
    /** Span this emission belongs to (hex); empty if none. */
    span_id: string
    /** Per-emission attributes (high-cardinality labels on the data point). */
    attributes: _MetricEventSampleApiAttributes
    /** Attributes of the resource (host, pod, service version) that emitted the metric. */
    resource_attributes: _MetricEventSampleApiResourceAttributes
}

export interface _MetricSamplesResponseApi {
    /** Raw emissions ordered by timestamp descending. */
    results: _MetricEventSampleApi[]
}

export interface _MetricNameApi {
    /** Metric name as it appears in the team's data. */
    name: string
    /** OTel metric type (gauge, sum, histogram, summary, exponential_histogram). */
    metric_type: string
}

export interface _MetricNamesResponseApi {
    /** Distinct metric names ordered by recent activity. */
    results: _MetricNameApi[]
}

export interface PipelineFilterApi {
    /**
     * Attribute name to filter on (e.g. 'k8s.pod.name').
     * @maxLength 255
     */
    key: string
    /**
     * Comparison operator: one of 'eq', 'neq', 'regex', 'not_regex'.
     * @maxLength 16
     */
    op?: string
    /**
     * Value to compare against; the pattern for regex operators.
     * @maxLength 1024
     */
    value: string
    /**
     * Where the attribute lives: 'resource', 'attribute', or 'auto'.
     * @maxLength 16
     */
    scope?: string
}

export interface PipelineThresholdBoundsApi {
    /**
     * Values below this breach the severity. Omit for no lower bound.
     * @nullable
     */
    lower?: number | null
    /**
     * Values above this breach the severity. Omit for no upper bound.
     * @nullable
     */
    upper?: number | null
}

export interface PipelineThresholdsApi {
    /** Bounds whose breach marks the stat degraded. */
    warn?: PipelineThresholdBoundsApi | null
    /** Bounds whose breach marks the stat critical. */
    crit?: PipelineThresholdBoundsApi | null
}

export interface PipelineBreakdownApi {
    /**
     * Label to split the stat's breakdown table by (e.g. 'partition_id').
     * @maxLength 255
     */
    group_by_key: string
    /**
     * Rows shown before the remainder rolls into one 'others' row.
     * @minimum 1
     * @maximum 20
     */
    top_n?: number
    /**
     * Attribute scope: 'resource', 'attribute', or 'auto'.
     * @maxLength 16
     */
    scope?: string
}

export interface PipelineStatApi {
    /**
     * Stat id, unique within its node.
     * @maxLength 64
     */
    id: string
    /**
     * Display label for the stat.
     * @maxLength 120
     */
    label: string
    /**
     * Display format hint: 'rate', 'bytes', 'pct', 'count', or 'duration'.
     * @maxLength 16
     */
    format?: string
    /**
     * Exact ingested metric name this stat queries.
     * @maxLength 255
     */
    metric_name: string
    /**
     * Aggregation per time bucket: 'sum', 'avg', 'count', 'rate', 'increase', 'quantile', or 'histogram_quantile'.
     * @maxLength 32
     */
    aggregation?: string
    /**
     * Quantile in (0, 1) for the quantile aggregations.
     * @minimum 0
     * @maximum 1
     * @nullable
     */
    quantile?: number | null
    /**
     * Optional OTel metric type constraint (e.g. 'gauge', 'sum', 'histogram').
     * @maxLength 32
     * @nullable
     */
    metric_type?: string | null
    /** Label predicates ANDed onto the stat's query. */
    filters?: PipelineFilterApi[]
    /** Warn/crit bounds evaluated against the stat's latest value. */
    thresholds?: PipelineThresholdsApi | null
    /** Optional per-label breakdown table under the stat. */
    breakdown?: PipelineBreakdownApi | null
}

export interface PipelineLinkApi {
    /**
     * Link text shown on the drill panel.
     * @maxLength 120
     */
    label: string
    /**
     * Destination URL.
     * @maxLength 2048
     */
    url: string
}

export interface PipelineNodeApi {
    /**
     * Node id, unique within the pipeline; edges reference it.
     * @maxLength 64
     */
    id: string
    /**
     * Display name of the component.
     * @maxLength 120
     */
    name: string
    /**
     * Free-form component kind subtitle.
     * @maxLength 120
     */
    kind?: string
    /** Health stats on this node (at most 12). */
    stats: PipelineStatApi[]
    /**
     * Stat ids shown on the collapsed node card, in order.
     * @items.maxLength 64
     */
    headline_stat_ids?: string[]
    /** External deep links shown on the drill panel. */
    links?: PipelineLinkApi[]
    /** Free-form operator note shown on the drill panel. */
    note?: string
}

export interface PipelineEdgeApi {
    /**
     * Upstream node id.
     * @maxLength 64
     */
    source: string
    /**
     * Downstream node id.
     * @maxLength 64
     */
    target: string
    /**
     * Metric measuring throughput along this edge.
     * @maxLength 255
     */
    metric_name: string
    /**
     * Aggregation per time bucket; same vocabulary as stats.
     * @maxLength 32
     */
    aggregation?: string
    /**
     * Quantile in (0, 1) for the quantile aggregations.
     * @minimum 0
     * @maximum 1
     * @nullable
     */
    quantile?: number | null
    /**
     * Optional OTel metric type constraint.
     * @maxLength 32
     * @nullable
     */
    metric_type?: string | null
    /** Label predicates ANDed onto the edge's query. */
    filters?: PipelineFilterApi[]
    /**
     * How far back the comparison window sits, e.g. '-7d', '-24h', '-1w'.
     * @maxLength 16
     */
    baseline_offset?: string
    /** Current/baseline ratio at which the edge renders hot. Must exceed 1. */
    hot_multiplier?: number
}

export interface PipelineVariableApi {
    /**
     * Variable key referenced when evaluating.
     * @maxLength 64
     */
    key: string
    /**
     * Display label of the selector.
     * @maxLength 120
     */
    label: string
    /**
     * Metric label the chosen value filters on (e.g. 'k8s.cluster.name').
     * @maxLength 255
     */
    filter_key: string
    /**
     * Allowed values; empty accepts any value.
     * @items.maxLength 255
     */
    options?: string[]
    /**
     * Value applied when none is passed to evaluate.
     * @maxLength 255
     * @nullable
     */
    default?: string | null
}

export interface PipelineConfigApi {
    /** Topology nodes (at most 20). */
    nodes: PipelineNodeApi[]
    /** Directed flows between nodes; the graph must stay acyclic. */
    edges?: PipelineEdgeApi[]
    /** Pipeline-level selectors injected into every query. */
    variables?: PipelineVariableApi[]
}

export interface PipelineActorApi {
    /** User id. */
    id: number
    /** User email. */
    email: string
    /** User first name. */
    first_name: string
}

/**
 * Read shape of a stored pipeline (mirrors `MetricsPipelineRecord`).
 */
export interface MetricsPipelineApi {
    /** Pipeline UUID. */
    id: string
    /** Display name of the pipeline. */
    name: string
    /** What this pipeline observes and who owns it. */
    description: string
    /** The topology: nodes with health stats, edges with baselines. */
    config: PipelineConfigApi
    /** Disabled pipelines stay listed but are not evaluated. */
    enabled: boolean
    /** Creation time, ISO 8601. */
    created_at: string
    /** User who created the pipeline. */
    created_by: PipelineActorApi | null
    /**
     * Last update time, ISO 8601.
     * @nullable
     */
    updated_at: string | null
}

export interface PipelineListResponseApi {
    /** Total pipelines for the team. */
    count: number
    /** The team's pipelines, newest first. */
    results: MetricsPipelineApi[]
}

/**
 * Write shape for create/update. `config` is fully revalidated by
 * `parse_pipeline_config` on every write.
 */
export interface MetricsPipelineWriteApi {
    /**
     * Display name of the pipeline.
     * @maxLength 400
     */
    name: string
    /** What this pipeline observes and who owns it. */
    description?: string
    /** The topology: nodes with health stats, edges with baselines. */
    config: PipelineConfigApi
    /** Disabled pipelines stay listed but are not evaluated. */
    enabled?: boolean
}

/**
 * Write shape for create/update. `config` is fully revalidated by
 * `parse_pipeline_config` on every write.
 */
export interface PatchedMetricsPipelineWriteApi {
    /**
     * Display name of the pipeline.
     * @maxLength 400
     */
    name?: string
    /** What this pipeline observes and who owns it. */
    description?: string
    /** The topology: nodes with health stats, edges with baselines. */
    config?: PipelineConfigApi
    /** Disabled pipelines stay listed but are not evaluated. */
    enabled?: boolean
}

/**
 * Variable values keyed by variable key; unset variables fall back to their defaults.
 */
export type PipelineEvaluateRequestApiVariables = { [key: string]: string }

export interface PipelineEvaluateRequestApi {
    /** Variable values keyed by variable key; unset variables fall back to their defaults. */
    variables?: PipelineEvaluateRequestApiVariables
    /**
     * Window start (ISO 8601). Defaults to 30 minutes ago.
     * @nullable
     */
    date_from?: string | null
    /**
     * Window end (ISO 8601), exclusive. Defaults to now.
     * @nullable
     */
    date_to?: string | null
}

export interface PipelineBreakdownRowApi {
    /** Label value of the row (e.g. the partition id). */
    label: string
    /** Latest reported value for the row. */
    value: number
}

export interface PipelineStatResultApi {
    /** Stat id from the config. */
    id: string
    /** Display label from the config. */
    label: string
    /** Display format hint from the config. */
    format: string
    /**
     * Latest reported value; null when the stat is silent.
     * @nullable
     */
    value: number | null
    /** Health verdict: 'healthy', 'degraded', 'critical', or 'no_data'. */
    state: string
    /** Top breakdown rows, when the stat configures a breakdown. */
    breakdown_rows: PipelineBreakdownRowApi[]
    /** Rollup of the rows beyond top_n; null when nothing was rolled up. */
    breakdown_others: PipelineBreakdownRowApi | null
}

export interface PipelineNodeResultApi {
    /** Node id from the config. */
    id: string
    /** Worst reporting stat's verdict; 'no_data' when every stat is silent. */
    state: string
    /** Per-stat verdicts, in config order. */
    stats: PipelineStatResultApi[]
}

export interface PipelinePointApi {
    /** Bucket start, ISO 8601. */
    time: string
    /**
     * Bucket value; null renders a gap.
     * @nullable
     */
    value: number | null
}

export interface PipelineEdgeResultApi {
    /** Upstream node id. */
    source: string
    /** Downstream node id. */
    target: string
    /**
     * Mean throughput over the current window.
     * @nullable
     */
    current_value: number | null
    /**
     * Mean throughput over the baseline window.
     * @nullable
     */
    baseline_value: number | null
    /**
     * current/baseline ratio; null when the baseline had no signal.
     * @nullable
     */
    multiplier: number | null
    /** True when the multiplier reached the edge's hot_multiplier. */
    hot: boolean
    /** Current-window series for the sparkline. */
    points: PipelinePointApi[]
}

export interface PipelineAlertApi {
    /** 'warning' or 'critical'. */
    severity: string
    /** Node whose stat breached. */
    node_id: string
    /** The breached stat. */
    stat_id: string
    /** Human-readable alert line for the strip. */
    message: string
}

export interface PipelineEvaluationApi {
    /** Per-node verdicts, in config order. */
    nodes: PipelineNodeResultApi[]
    /** Per-edge throughput vs baseline, in config order. */
    edges: PipelineEdgeResultApi[]
    /** Derived alert strip, critical entries first. */
    alerts: PipelineAlertApi[]
    /** Evaluated window start, ISO 8601. */
    date_from: string
    /** Evaluated window end, ISO 8601. */
    date_to: string
}

export type MetricsAttributeValuesRetrieveParams = {
    /**
     * Lower bound (inclusive) of the window values are suggested from. ISO 8601. Defaults to 7 days ago.
     * @nullable
     */
    dateFrom?: string | null
    /**
     * Upper bound (exclusive) of the window. ISO 8601. Defaults to now.
     * @nullable
     */
    dateTo?: string | null
    /**
     * Attribute key to list values for (e.g. 'env'). 'service_name'/'service.name' list service names.
     * @minLength 1
     * @maxLength 255
     */
    key: string
    /**
     * Max number of values to return. Defaults to 100; maximum 1000.
     * @minimum 1
     * @maximum 1000
     */
    limit?: number
    /**
     * Substring filter (case-insensitive) applied to values. Named 'value' to match the property-values autocomplete convention.
     * @maxLength 1024
     */
    value?: string
}

export type MetricsAttributesRetrieveParams = {
    /**
     * Lower bound (inclusive) of the window keys are suggested from. ISO 8601. Defaults to 7 days ago.
     * @nullable
     */
    dateFrom?: string | null
    /**
     * Upper bound (exclusive) of the window. ISO 8601. Defaults to now.
     * @nullable
     */
    dateTo?: string | null
    /**
     * Max number of keys to return. Defaults to 100; maximum 1000.
     * @minimum 1
     * @maximum 1000
     */
    limit?: number
    /**
     * Substring filter (case-insensitive) applied to attribute keys.
     * @maxLength 255
     */
    search?: string
}

export type MetricsValuesRetrieveParams = {
    /**
     * Max number of names to return. Defaults to 100; maximum 1000.
     * @minimum 1
     * @maximum 1000
     */
    limit?: number
    /**
     * Comma-separated services to narrow the list to, e.g. `service=web,worker`. Omit for every service. Send it empty to select only series whose sender did not set `service.name`. A service name containing a comma cannot be selected.
     * @maxLength 1024
     */
    service?: string
    /**
     * Substring filter (case-insensitive) applied to metric names.
     * @maxLength 255
     */
    value?: string
}
