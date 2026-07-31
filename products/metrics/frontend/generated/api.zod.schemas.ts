/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const AppMetricSeriesApi = zod.object({
    name: zod.string(),
    values: zod.array(zod.number()),
})

export type AppMetricSeriesApi = zod.input<typeof AppMetricSeriesApi>
export type AppMetricSeriesApiOutput = zod.output<typeof AppMetricSeriesApi>

export const AppMetricsResponseApi = zod.object({
    labels: zod.array(zod.string()),
    series: zod.array(AppMetricSeriesApi),
})

export type AppMetricsResponseApi = zod.input<typeof AppMetricsResponseApi>
export type AppMetricsResponseApiOutput = zod.output<typeof AppMetricsResponseApi>

export const AppMetricsTotalsResponseApi = zod.object({
    totals: zod.record(zod.string(), zod.number()),
})

export type AppMetricsTotalsResponseApi = zod.input<typeof AppMetricsTotalsResponseApi>
export type AppMetricsTotalsResponseApiOutput = zod.output<typeof AppMetricsTotalsResponseApi>

export const _MetricAttributeValueApi = zod.object({
    id: zod.string().describe('The attribute value (same as name; kept for picker compatibility).'),
    name: zod.string().describe('The attribute value.'),
    count: zod.number().describe('Number of data points observed with this value in the window.'),
})

export type _MetricAttributeValueApi = zod.input<typeof _MetricAttributeValueApi>
export type _MetricAttributeValueApiOutput = zod.output<typeof _MetricAttributeValueApi>

export const _MetricAttributeValuesResponseApi = zod.object({
    results: zod
        .array(_MetricAttributeValueApi)
        .describe('Observed values for the requested key, most frequent first.'),
})

export type _MetricAttributeValuesResponseApi = zod.input<typeof _MetricAttributeValuesResponseApi>
export type _MetricAttributeValuesResponseApiOutput = zod.output<typeof _MetricAttributeValuesResponseApi>

export const _MetricAttributeKeyApi = zod.object({
    name: zod.string().describe("Attribute key as it appears on the team's metrics (e.g. 'env', 'k8s.pod.name')."),
})

export type _MetricAttributeKeyApi = zod.input<typeof _MetricAttributeKeyApi>
export type _MetricAttributeKeyApiOutput = zod.output<typeof _MetricAttributeKeyApi>

export const _MetricAttributeKeysResponseApi = zod.object({
    results: zod
        .array(_MetricAttributeKeyApi)
        .describe('Distinct attribute keys (datapoint and resource attributes merged), most frequent first.'),
    count: zod.number().describe('Number of keys returned.'),
})

export type _MetricAttributeKeysResponseApi = zod.input<typeof _MetricAttributeKeysResponseApi>
export type _MetricAttributeKeysResponseApiOutput = zod.output<typeof _MetricAttributeKeysResponseApi>

export const AggregationEnumApi = zod
    .enum(['sum', 'avg', 'count', 'p95', 'rate', 'increase', 'histogram_quantile'])
    .describe(
        '\* `sum` - sum\n\* `avg` - avg\n\* `count` - count\n\* `p95` - p95\n\* `rate` - rate\n\* `increase` - increase\n\* `histogram_quantile` - histogram_quantile'
    )

export type AggregationEnumApi = zod.input<typeof AggregationEnumApi>
export type AggregationEnumApiOutput = zod.output<typeof AggregationEnumApi>

export const OpEnumApi = zod
    .enum(['eq', 'neq', 'regex', 'not_regex'])
    .describe('\* `eq` - eq\n\* `neq` - neq\n\* `regex` - regex\n\* `not_regex` - not_regex')

export type OpEnumApi = zod.input<typeof OpEnumApi>
export type OpEnumApiOutput = zod.output<typeof OpEnumApi>

export const MetricAttributeScopeEnumApi = zod
    .enum(['resource', 'attribute', 'auto'])
    .describe('\* `resource` - resource\n\* `attribute` - attribute\n\* `auto` - auto')

export type MetricAttributeScopeEnumApi = zod.input<typeof MetricAttributeScopeEnumApi>
export type MetricAttributeScopeEnumApiOutput = zod.output<typeof MetricAttributeScopeEnumApi>

export const _metricFilterApiKeyMax = 255

export const _metricFilterApiOpDefault = `eq`
export const _metricFilterApiValueMax = 1024

export const _metricFilterApiScopeDefault = `auto`

export const _MetricFilterApi = zod.object({
    key: zod
        .string()
        .max(_metricFilterApiKeyMax)
        .describe("Attribute name to filter on, without any type-tag suffix (e.g. 'k8s.pod.name', 'env')."),
    op: OpEnumApi.default(_metricFilterApiOpDefault).describe(
        "Comparison operator. 'regex'\/'not_regex' use RE2 syntax. Negative operators also match rows that lack the key entirely, mirroring Prometheus negative matchers.\n\n\* `eq` - eq\n\* `neq` - neq\n\* `regex` - regex\n\* `not_regex` - not_regex"
    ),
    value: zod
        .string()
        .max(_metricFilterApiValueMax)
        .describe('Value to compare against. For regex operators this is the pattern.'),
    scope: MetricAttributeScopeEnumApi.default(_metricFilterApiScopeDefault).describe(
        "Where the attribute lives: 'resource' = per-target resource attributes (k8s.pod.name, service.version), 'attribute' = per-datapoint attributes (http.method, path), 'auto' = resource first with per-datapoint fallback. Use 'auto' unless you know the exact scope.\n\n\* `resource` - resource\n\* `attribute` - attribute\n\* `auto` - auto"
    ),
})

export type _MetricFilterApi = zod.input<typeof _MetricFilterApi>
export type _MetricFilterApiOutput = zod.output<typeof _MetricFilterApi>

export const _metricAnomalyBodyApiMetricNameMax = 255

export const _metricAnomalyBodyApiQuantileMin = 0
export const _metricAnomalyBodyApiQuantileMax = 1

export const _metricAnomalyBodyApiCandidateKeysItemMax = 255

export const _MetricAnomalyBodyApi = zod.object({
    metricName: zod
        .string()
        .max(_metricAnomalyBodyApiMetricNameMax)
        .describe("Exact metric name to characterize (e.g. 'metrics_rate_limiter_message_lag_seconds')."),
    anomalyFrom: zod.iso
        .datetime({ offset: true })
        .describe(
            'Start of the suspicious window (inclusive). ISO 8601 — e.g. when the alert fired or the graph started looking wrong.'
        ),
    anomalyTo: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('End of the suspicious window (exclusive). Defaults to now.'),
    baselineFrom: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('Start of the healthy comparison window. Defaults to one anomaly-window-length before baselineTo.'),
    baselineTo: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('End of the healthy comparison window. Defaults to anomalyFrom. Must not extend past anomalyFrom.'),
    aggregation: zod
        .union([AggregationEnumApi, zod.null()])
        .optional()
        .describe(
            "Aggregation to characterize. Omit to auto-pick from the metric's OTel type (counter -> rate, gauge -> avg, histogram -> histogram_quantile 0.95).\n\n\* `sum` - sum\n\* `avg` - avg\n\* `count` - count\n\* `p95` - p95\n\* `rate` - rate\n\* `increase` - increase\n\* `histogram_quantile` - histogram_quantile"
        ),
    quantile: zod
        .number()
        .min(_metricAnomalyBodyApiQuantileMin)
        .max(_metricAnomalyBodyApiQuantileMax)
        .nullish()
        .describe('Quantile for histogram_quantile. Defaults to 0.95.'),
    filters: zod
        .array(_MetricFilterApi)
        .optional()
        .describe('Label predicates narrowing which series are characterized.'),
    candidateKeys: zod
        .array(zod.string().max(_metricAnomalyBodyApiCandidateKeysItemMax))
        .optional()
        .describe(
            'Label keys to drill into when finding which label values moved. Omit to auto-discover the most common keys on this metric (plus service_name). Max 4 are used.'
        ),
})

export type _MetricAnomalyBodyApi = zod.input<typeof _MetricAnomalyBodyApi>
export type _MetricAnomalyBodyApiOutput = zod.output<typeof _MetricAnomalyBodyApi>

export const _MetricAnomalyRequestApi = zod.object({
    query: _MetricAnomalyBodyApi.describe('The anomaly characterization to run.'),
})

export type _MetricAnomalyRequestApi = zod.input<typeof _MetricAnomalyRequestApi>
export type _MetricAnomalyRequestApiOutput = zod.output<typeof _MetricAnomalyRequestApi>

export const MetricAnomalyDirectionEnumApi = zod
    .enum(['up', 'down', 'flat'])
    .describe('\* `up` - up\n\* `down` - down\n\* `flat` - flat')

export type MetricAnomalyDirectionEnumApi = zod.input<typeof MetricAnomalyDirectionEnumApi>
export type MetricAnomalyDirectionEnumApiOutput = zod.output<typeof MetricAnomalyDirectionEnumApi>

export const _MetricAnomalyDimensionApi = zod.object({
    key: zod.string().describe('Label key that was drilled into.'),
    label: zod.string().describe('Label value this row describes.'),
    baseline_value: zod.number().describe('Mean value over the baseline window for this label value.'),
    anomaly_value: zod.number().describe('Mean value over the anomaly window for this label value.'),
    change_ratio: zod
        .number()
        .describe('anomaly_value \/ baseline_value. A zero baseline yields the anomaly value itself (new traffic).'),
})

export type _MetricAnomalyDimensionApi = zod.input<typeof _MetricAnomalyDimensionApi>
export type _MetricAnomalyDimensionApiOutput = zod.output<typeof _MetricAnomalyDimensionApi>

export const _MetricQueryPointApi = zod.object({
    time: zod.string().describe('Bucket start as ISO 8601 timestamp.'),
    value: zod
        .number()
        .nullable()
        .describe(
            "Aggregated value for the bucket. Null when the aggregate isn't representable (e.g. float overflow) — render as a gap."
        ),
})

export type _MetricQueryPointApi = zod.input<typeof _MetricQueryPointApi>
export type _MetricQueryPointApiOutput = zod.output<typeof _MetricQueryPointApi>

export const _MetricSeriesApi = zod.object({
    labels: zod
        .record(zod.string(), zod.string())
        .describe('Label values identifying this series. Empty for an ungrouped query.'),
    points: zod.array(_MetricQueryPointApi).describe('Time-bucketed points, ordered by time ascending.'),
    metric_name: zod.string().nullish().describe('Metric the series was computed from. Null for formula results.'),
    clause: zod.string().nullish().describe('Name of the query clause that produced this series.'),
})

export type _MetricSeriesApi = zod.input<typeof _MetricSeriesApi>
export type _MetricSeriesApiOutput = zod.output<typeof _MetricSeriesApi>

export const _MetricAnomalyReportApi = zod.object({
    metric_name: zod.string().describe('Metric that was characterized.'),
    aggregation: zod.string().describe('Aggregation used (auto-picked when not specified).'),
    interval: zod.string().describe('Bucket size of the analysis grid.'),
    baseline_from: zod.string().describe('Baseline window start, ISO 8601.'),
    baseline_to: zod.string().describe('Baseline window end, ISO 8601.'),
    anomaly_from: zod.string().describe('Anomaly window start, ISO 8601.'),
    anomaly_to: zod.string().describe('Anomaly window end, ISO 8601.'),
    baseline_mean: zod.number().describe('Mean over the baseline window.'),
    baseline_stddev: zod.number().describe('Population stddev over the baseline window.'),
    anomaly_mean: zod.number().describe('Mean over the anomaly window.'),
    anomaly_peak: zod.number().describe('Maximum bucket value in the anomaly window.'),
    change_ratio: zod.number().describe('anomaly_mean \/ baseline_mean. A zero baseline yields anomaly_mean itself.'),
    direction: MetricAnomalyDirectionEnumApi.describe(
        'Which way the metric moved versus the baseline.\n\n\* `up` - up\n\* `down` - down\n\* `flat` - flat'
    ),
    onset_time: zod
        .string()
        .nullable()
        .describe(
            'First bucket clearly outside the baseline range (3 stddevs or 50% relative change), or null if no clear onset.'
        ),
    top_movers: zod
        .array(_MetricAnomalyDimensionApi)
        .describe(
            'Label values whose behavior changed the most between windows, largest change first. Empty when nothing moved or the metric has no labels.'
        ),
    series: _MetricSeriesApi.describe(
        'The metric across baseline + anomaly windows on one grid, for plotting or further inspection.'
    ),
})

export type _MetricAnomalyReportApi = zod.input<typeof _MetricAnomalyReportApi>
export type _MetricAnomalyReportApiOutput = zod.output<typeof _MetricAnomalyReportApi>

export const _HasMetricsResponseApi = zod.object({
    hasMetrics: zod.boolean().describe('Whether the team has ingested any metrics.'),
})

export type _HasMetricsResponseApi = zod.input<typeof _HasMetricsResponseApi>
export type _HasMetricsResponseApiOutput = zod.output<typeof _HasMetricsResponseApi>

export const OtelMetricTypeEnumApi = zod
    .enum(['gauge', 'sum', 'histogram', 'exponential_histogram', 'summary'])
    .describe(
        '\* `gauge` - gauge\n\* `sum` - sum\n\* `histogram` - histogram\n\* `exponential_histogram` - exponential_histogram\n\* `summary` - summary'
    )

export type OtelMetricTypeEnumApi = zod.input<typeof OtelMetricTypeEnumApi>
export type OtelMetricTypeEnumApiOutput = zod.output<typeof OtelMetricTypeEnumApi>

export const _metricGroupByApiKeyMax = 255

export const _metricGroupByApiScopeDefault = `auto`

export const _MetricGroupByApi = zod.object({
    key: zod
        .string()
        .max(_metricGroupByApiKeyMax)
        .describe("Attribute name to split series by (e.g. 'k8s.pod.name', 'env')."),
    scope: MetricAttributeScopeEnumApi.default(_metricGroupByApiScopeDefault).describe(
        "Where the attribute lives; same semantics as filter scope. Use 'auto' unless you know the exact scope.\n\n\* `resource` - resource\n\* `attribute` - attribute\n\* `auto` - auto"
    ),
})

export type _MetricGroupByApi = zod.input<typeof _MetricGroupByApi>
export type _MetricGroupByApiOutput = zod.output<typeof _MetricGroupByApi>

export const MetricQueryIntervalEnumApi = zod
    .enum(['second', 'minute', 'minute_5', 'minute_15', 'hour', 'hour_6', 'day', 'week'])
    .describe(
        '\* `second` - second\n\* `minute` - minute\n\* `minute_5` - minute_5\n\* `minute_15` - minute_15\n\* `hour` - hour\n\* `hour_6` - hour_6\n\* `day` - day\n\* `week` - week'
    )

export type MetricQueryIntervalEnumApi = zod.input<typeof MetricQueryIntervalEnumApi>
export type MetricQueryIntervalEnumApiOutput = zod.output<typeof MetricQueryIntervalEnumApi>

export const _metricClauseApiNameMax = 64

export const _metricClauseApiMetricNameMax = 255

export const _metricClauseApiAggregationDefault = `sum`
export const _metricClauseApiQuantileMin = 0
export const _metricClauseApiQuantileMax = 1

export const _MetricClauseApi = zod.object({
    name: zod.string().max(_metricClauseApiNameMax).describe("Clause name a formula refers to (e.g. 'a')."),
    metricName: zod.string().max(_metricClauseApiMetricNameMax).describe('Exact metric name this clause queries.'),
    metricType: zod
        .union([OtelMetricTypeEnumApi, zod.null()])
        .optional()
        .describe(
            "Constrain the query to one metric type. A name can exist as several types (e.g. a counter and a gauge); without this, rows of every type sharing the name are blended into one aggregate. Get the type from 'metric-names-list'.\n\n\* `gauge` - gauge\n\* `sum` - sum\n\* `histogram` - histogram\n\* `exponential_histogram` - exponential_histogram\n\* `summary` - summary"
        ),
    aggregation: AggregationEnumApi.default(_metricClauseApiAggregationDefault).describe(
        'Aggregation applied per time bucket; same semantics as the top-level aggregation.\n\n\* `sum` - sum\n\* `avg` - avg\n\* `count` - count\n\* `p95` - p95\n\* `rate` - rate\n\* `increase` - increase\n\* `histogram_quantile` - histogram_quantile'
    ),
    quantile: zod
        .number()
        .min(_metricClauseApiQuantileMin)
        .max(_metricClauseApiQuantileMax)
        .nullish()
        .describe("Quantile in (0, 1) for 'histogram_quantile'."),
    filters: zod.array(_MetricFilterApi).optional().describe('Label predicates ANDed together for this clause.'),
    groupBy: zod.array(_MetricGroupByApi).optional().describe('Labels to split this clause into separate series by.'),
})

export type _MetricClauseApi = zod.input<typeof _MetricClauseApi>
export type _MetricClauseApiOutput = zod.output<typeof _MetricClauseApi>

export const _metricQueryBodyApiMetricNameMax = 255

export const _metricQueryBodyApiAggregationDefault = `sum`
export const _metricQueryBodyApiQuantileMin = 0
export const _metricQueryBodyApiQuantileMax = 1

export const _metricQueryBodyApiFormulaMax = 512

export const _MetricQueryBodyApi = zod.object({
    metricName: zod
        .string()
        .max(_metricQueryBodyApiMetricNameMax)
        .optional()
        .describe(
            "Exact metric name to query (e.g. 'http.server.duration'). Single-clause shorthand — mutually exclusive with 'clauses'."
        ),
    metricType: zod
        .union([OtelMetricTypeEnumApi, zod.null()])
        .optional()
        .describe(
            "Constrain the query to one metric type. A name can exist as several types (e.g. a counter and a gauge); without this, rows of every type sharing the name are blended into one aggregate. Get the type from 'metric-names-list'.\n\n\* `gauge` - gauge\n\* `sum` - sum\n\* `histogram` - histogram\n\* `exponential_histogram` - exponential_histogram\n\* `summary` - summary"
        ),
    aggregation: AggregationEnumApi.default(_metricQueryBodyApiAggregationDefault).describe(
        "Aggregation applied per time bucket. 'rate' (per-second) and 'increase' are counter-aware: per-series deltas with Prometheus counter-reset handling, temporality-aware (delta-temporality samples count as-is). 'histogram_quantile' interpolates from OTel histogram buckets and requires 'quantile'.\n\n\* `sum` - sum\n\* `avg` - avg\n\* `count` - count\n\* `p95` - p95\n\* `rate` - rate\n\* `increase` - increase\n\* `histogram_quantile` - histogram_quantile"
    ),
    quantile: zod
        .number()
        .min(_metricQueryBodyApiQuantileMin)
        .max(_metricQueryBodyApiQuantileMax)
        .nullish()
        .describe("Quantile in (0, 1) for 'histogram_quantile' (e.g. 0.95). Ignored for other aggregations."),
    filters: zod
        .array(_MetricFilterApi)
        .optional()
        .describe('Label predicates ANDed together. Rows must satisfy every filter.'),
    groupBy: zod
        .array(_MetricGroupByApi)
        .optional()
        .describe(
            'Labels to split the result into separate series by. Series share one time grid and are capped at the 100 largest.'
        ),
    interval: zod
        .union([MetricQueryIntervalEnumApi, zod.null()])
        .optional()
        .describe(
            'Bucket size for the shared time grid. Omit to auto-pick (~60 buckets across the range).\n\n\* `second` - second\n\* `minute` - minute\n\* `minute_5` - minute_5\n\* `minute_15` - minute_15\n\* `hour` - hour\n\* `hour_6` - hour_6\n\* `day` - day\n\* `week` - week'
        ),
    clauses: zod
        .array(_MetricClauseApi)
        .optional()
        .describe(
            "Full multi-clause form: each clause is an independent metric selection sharing the request's time grid (maximum 10). Mutually exclusive with 'metricName'."
        ),
    formula: zod
        .string()
        .max(_metricQueryBodyApiFormulaMax)
        .nullish()
        .describe(
            "Arithmetic over clause names evaluated server-side per grid point, e.g. '(a - b) \/ a'. Supports + - \* \/ and parentheses; division by zero yields 0. When set, only the formula result series are returned."
        ),
    dateFrom: zod.iso.datetime({ offset: true }).describe('Lower bound (inclusive) for the query range. ISO 8601.'),
    dateTo: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('Upper bound (exclusive) for the query range. Defaults to now if omitted.'),
})

export type _MetricQueryBodyApi = zod.input<typeof _MetricQueryBodyApi>
export type _MetricQueryBodyApiOutput = zod.output<typeof _MetricQueryBodyApi>

export const _MetricQueryRequestApi = zod.object({
    query: _MetricQueryBodyApi.describe('The metric query to execute.'),
})

export type _MetricQueryRequestApi = zod.input<typeof _MetricQueryRequestApi>
export type _MetricQueryRequestApiOutput = zod.output<typeof _MetricQueryRequestApi>

export const _MetricQueryResponseApi = zod.object({
    results: zod
        .array(_MetricSeriesApi)
        .describe(
            'One series per (clause, label-set). A single ungrouped query returns exactly one series with empty labels.'
        ),
})

export type _MetricQueryResponseApi = zod.input<typeof _MetricQueryResponseApi>
export type _MetricQueryResponseApiOutput = zod.output<typeof _MetricQueryResponseApi>

export const _metricSamplesBodyApiMetricNameMax = 255

export const _metricSamplesBodyApiTraceIdMax = 255

export const _metricSamplesBodyApiLimitDefault = 100
export const _metricSamplesBodyApiLimitMax = 1000

export const _MetricSamplesBodyApi = zod.object({
    metricName: zod
        .string()
        .max(_metricSamplesBodyApiMetricNameMax)
        .describe("Exact metric name to list raw emissions for (e.g. 'http.server.duration')."),
    dateFrom: zod.iso.datetime({ offset: true }).describe('Lower bound (inclusive) for the sample window. ISO 8601.'),
    dateTo: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('Upper bound (exclusive) for the sample window. Defaults to now if omitted.'),
    traceId: zod
        .string()
        .max(_metricSamplesBodyApiTraceIdMax)
        .optional()
        .describe(
            'Restrict to emissions on this trace (hex trace id, as the tracing product uses) — the reverse metric->trace pivot. Omit for all traces.'
        ),
    limit: zod
        .number()
        .min(1)
        .max(_metricSamplesBodyApiLimitMax)
        .default(_metricSamplesBodyApiLimitDefault)
        .describe('Max emissions to return, newest first. Defaults to 100, capped at 1000.'),
})

export type _MetricSamplesBodyApi = zod.input<typeof _MetricSamplesBodyApi>
export type _MetricSamplesBodyApiOutput = zod.output<typeof _MetricSamplesBodyApi>

export const _MetricSamplesRequestApi = zod.object({
    query: _MetricSamplesBodyApi.describe('The raw-emissions query to execute.'),
})

export type _MetricSamplesRequestApi = zod.input<typeof _MetricSamplesRequestApi>
export type _MetricSamplesRequestApiOutput = zod.output<typeof _MetricSamplesRequestApi>

export const _MetricEventSampleApi = zod.object({
    timestamp: zod.string().describe('When the metric was emitted, ISO 8601.'),
    metric_name: zod.string().describe('Metric this emission belongs to.'),
    metric_type: zod.string().describe('OTel metric type: gauge, sum, histogram, summary, or exponential_histogram.'),
    value: zod
        .number()
        .describe('The emitted value. For histogram\/summary points this is the distribution sum; pair with count.'),
    count: zod
        .number()
        .describe(
            'Observations behind this point: 1 for gauges\/counters, the distribution count for histograms\/summaries.'
        ),
    unit: zod.string().describe('Unit of the value, if any.'),
    aggregation_temporality: zod
        .string()
        .describe("For counters: 'delta' or 'cumulative' (decides whether rate() must diff). Empty for gauges."),
    is_monotonic: zod.boolean().describe('True for monotonically increasing counters.'),
    service_name: zod.string().describe('Service that emitted the metric.'),
    trace_id: zod
        .string()
        .describe(
            'Trace this emission belongs to (hex, same form the tracing product uses); empty if none. Use it to pivot to the trace.'
        ),
    span_id: zod.string().describe('Span this emission belongs to (hex); empty if none.'),
    attributes: zod
        .record(zod.string(), zod.string())
        .describe('Per-emission attributes (high-cardinality labels on the data point).'),
    resource_attributes: zod
        .record(zod.string(), zod.string())
        .describe('Attributes of the resource (host, pod, service version) that emitted the metric.'),
})

export type _MetricEventSampleApi = zod.input<typeof _MetricEventSampleApi>
export type _MetricEventSampleApiOutput = zod.output<typeof _MetricEventSampleApi>

export const _MetricSamplesResponseApi = zod.object({
    results: zod.array(_MetricEventSampleApi).describe('Raw emissions ordered by timestamp descending.'),
})

export type _MetricSamplesResponseApi = zod.input<typeof _MetricSamplesResponseApi>
export type _MetricSamplesResponseApiOutput = zod.output<typeof _MetricSamplesResponseApi>

export const _MetricNameApi = zod.object({
    name: zod.string().describe("Metric name as it appears in the team's data."),
    metric_type: zod.string().describe('OTel metric type (gauge, sum, histogram, summary, exponential_histogram).'),
})

export type _MetricNameApi = zod.input<typeof _MetricNameApi>
export type _MetricNameApiOutput = zod.output<typeof _MetricNameApi>

export const _MetricNamesResponseApi = zod.object({
    results: zod.array(_MetricNameApi).describe('Distinct metric names ordered by recent activity.'),
})

export type _MetricNamesResponseApi = zod.input<typeof _MetricNamesResponseApi>
export type _MetricNamesResponseApiOutput = zod.output<typeof _MetricNamesResponseApi>
