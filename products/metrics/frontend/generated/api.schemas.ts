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

/**
 * * `sum` - sum
 * * `avg` - avg
 * * `count` - count
 * * `p95` - p95
 */
export type AggregationEnumApi = (typeof AggregationEnumApi)[keyof typeof AggregationEnumApi]

export const AggregationEnumApi = {
    Sum: 'sum',
    Avg: 'avg',
    Count: 'count',
    P95: 'p95',
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
export type _MetricFilterScopeEnumApi = (typeof _MetricFilterScopeEnumApi)[keyof typeof _MetricFilterScopeEnumApi]

export const _MetricFilterScopeEnumApi = {
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
    /** Value to compare against. For regex operators this is the pattern. */
    value: string
    /** Where the attribute lives: 'resource' = per-target resource attributes (k8s.pod.name, service.version), 'attribute' = per-datapoint attributes (http.method, path), 'auto' = resource first with per-datapoint fallback. Use 'auto' unless you know the exact scope.
     *
     * * `resource` - resource
     * * `attribute` - attribute
     * * `auto` - auto */
    scope?: _MetricFilterScopeEnumApi
}

export interface _MetricQueryBodyApi {
    /**
     * Exact metric name to query (e.g. 'http.server.duration').
     * @maxLength 255
     */
    metricName: string
    /** Aggregation applied per time bucket.
     *
     * * `sum` - sum
     * * `avg` - avg
     * * `count` - count
     * * `p95` - p95 */
    aggregation?: AggregationEnumApi
    /** Label predicates ANDed together. Rows must satisfy every filter. */
    filters?: _MetricFilterApi[]
    /** Lower bound (inclusive) for the query range. ISO 8601. */
    dateFrom: string
    /** Upper bound (exclusive) for the query range. Defaults to now if omitted. */
    dateTo?: string
}

export interface _MetricQueryRequestApi {
    /** The metric query to execute. */
    query: _MetricQueryBodyApi
}

export interface _MetricQueryPointApi {
    /** Bucket start as ISO 8601 timestamp. */
    time: string
    /** Aggregated value for the bucket. */
    value: number
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

export interface _MetricQueryResponseApi {
    /** One series per (clause, label-set). A single ungrouped query returns exactly one series with empty labels. */
    results: _MetricSeriesApi[]
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

export type MetricsHasMetricsRetrieve200 = { [key: string]: unknown }

export type MetricsValuesRetrieveParams = {
    /**
     * Max number of names to return. Defaults to 100, capped at 1000.
     */
    limit?: number
    /**
     * Substring filter (case-insensitive) applied to metric names.
     */
    value?: string
}
