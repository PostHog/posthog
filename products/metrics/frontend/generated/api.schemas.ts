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

export interface _HasMetricsResponseApi {
    /** Whether the team has ingested any metrics. */
    hasMetrics: boolean
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
    /** Aggregation applied per time bucket. 'rate' (per-second) and 'increase' are counter-aware: per-series deltas with Prometheus counter-reset handling, temporality-aware (delta-temporality samples count as-is). 'histogram_quantile' interpolates from OTel histogram buckets and requires 'quantile'.
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
     * Restrict to emissions on this trace — the reverse metric->trace pivot. Omit for all traces.
     * @maxLength 255
     */
    traceId?: string
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
    /** Trace this emission belongs to; empty if none. Use it to pivot to the trace. */
    trace_id: string
    /** Span this emission belongs to; empty if none. */
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
     * Substring filter (case-insensitive) applied to metric names.
     * @maxLength 255
     */
    value?: string
}
