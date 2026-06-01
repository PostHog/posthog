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
 * `avg` - avg
 * `count` - count
 * `p95` - p95
 */
export type AggregationEnumApi = (typeof AggregationEnumApi)[keyof typeof AggregationEnumApi]

export const AggregationEnumApi = {
    Sum: 'sum',
    Avg: 'avg',
    Count: 'count',
    P95: 'p95',
} as const

export interface _MetricQueryBodyApi {
    /**
     * Exact metric name to query (e.g. 'http.server.duration').
     * @maxLength 255
     */
    metricName: string
    /** Aggregation applied per time bucket.

  * `sum` - sum
  * `avg` - avg
  * `count` - count
  * `p95` - p95 */
    aggregation?: AggregationEnumApi
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

export interface _MetricQueryResponseApi {
    /** Time-bucketed points, ordered by time ascending. */
    results: _MetricQueryPointApi[]
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
