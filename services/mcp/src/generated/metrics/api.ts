/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 6 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Observed values for one metric attribute key, most frequent first.
 * Backs the filter bar's value autocomplete.
 */
export const MetricsAttributeValuesRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const metricsAttributeValuesRetrieveQueryKeyMax = 255

export const metricsAttributeValuesRetrieveQueryLimitDefault = 100
export const metricsAttributeValuesRetrieveQueryLimitMax = 1000

export const metricsAttributeValuesRetrieveQueryValueDefault = ``
export const metricsAttributeValuesRetrieveQueryValueMax = 1024

export const MetricsAttributeValuesRetrieveQueryParams = () => zod.object({
    dateFrom: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe(
            'Lower bound (inclusive) of the window values are suggested from. ISO 8601. Defaults to 24 hours ago.'
        ),
    dateTo: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('Upper bound (exclusive) of the window. ISO 8601. Defaults to now.'),
    key: zod
        .string()
        .min(1)
        .max(metricsAttributeValuesRetrieveQueryKeyMax)
        .describe("Attribute key to list values for (e.g. 'env'). 'service_name'\/'service.name' list service names."),
    limit: zod
        .number()
        .min(1)
        .max(metricsAttributeValuesRetrieveQueryLimitMax)
        .default(metricsAttributeValuesRetrieveQueryLimitDefault)
        .describe('Max number of values to return. Defaults to 100; maximum 1000.'),
    value: zod
        .string()
        .max(metricsAttributeValuesRetrieveQueryValueMax)
        .default(metricsAttributeValuesRetrieveQueryValueDefault)
        .describe(
            "Substring filter (case-insensitive) applied to values. Named 'value' to match the property-values autocomplete convention."
        ),
})

/**
 * Attribute keys ordered by distinct series count, from highest to
 * lowest. `metricName` limits choices to one metric.
 */
export const MetricsAttributesRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const metricsAttributesRetrieveQueryLimitDefault = 100
export const metricsAttributesRetrieveQueryLimitMax = 1000

export const metricsAttributesRetrieveQueryMetricNameDefault = ``
export const metricsAttributesRetrieveQueryMetricNameMax = 255

export const metricsAttributesRetrieveQuerySearchDefault = ``
export const metricsAttributesRetrieveQuerySearchMax = 255

export const MetricsAttributesRetrieveQueryParams = () => zod.object({
    dateFrom: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('Lower bound (inclusive) of the window keys are suggested from. ISO 8601. Defaults to 24 hours ago.'),
    dateTo: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('Upper bound (exclusive) of the window. ISO 8601. Defaults to now.'),
    limit: zod
        .number()
        .min(1)
        .max(metricsAttributesRetrieveQueryLimitMax)
        .default(metricsAttributesRetrieveQueryLimitDefault)
        .describe('Max number of keys to return. Defaults to 100; maximum 1000.'),
    metricName: zod
        .string()
        .max(metricsAttributesRetrieveQueryMetricNameMax)
        .default(metricsAttributesRetrieveQueryMetricNameDefault)
        .describe('Exact metric name to limit attribute keys to. Omit to list keys across all metrics.'),
    search: zod
        .string()
        .max(metricsAttributesRetrieveQuerySearchMax)
        .default(metricsAttributesRetrieveQuerySearchDefault)
        .describe('Substring filter (case-insensitive) applied to attribute keys.'),
})

/**
 * Characterize a metric anomaly: compare an anomaly window against a
 * baseline, find the onset, and rank which label values moved.
 */
export const MetricsCharacterizeCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const metricsCharacterizeCreateBodyQueryOneMetricNameMax = 255

export const metricsCharacterizeCreateBodyQueryOneQuantileMin = 0
export const metricsCharacterizeCreateBodyQueryOneQuantileMax = 1

export const metricsCharacterizeCreateBodyQueryOneFiltersItemKeyMax = 255

export const metricsCharacterizeCreateBodyQueryOneFiltersItemOpDefault = `eq`
export const metricsCharacterizeCreateBodyQueryOneFiltersItemValueMax = 1024

export const metricsCharacterizeCreateBodyQueryOneFiltersItemScopeDefault = `auto`
export const metricsCharacterizeCreateBodyQueryOneCandidateKeysItemMax = 255

export const MetricsCharacterizeCreateBody = () => zod.object({
    query: zod
        .object({
            metricName: zod
                .string()
                .max(metricsCharacterizeCreateBodyQueryOneMetricNameMax)
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
                .describe(
                    'Start of the healthy comparison window. Defaults to one anomaly-window-length before baselineTo.'
                ),
            baselineTo: zod.iso
                .datetime({ offset: true })
                .optional()
                .describe(
                    'End of the healthy comparison window. Defaults to anomalyFrom. Must not extend past anomalyFrom.'
                ),
            aggregation: zod
                .union([
                    zod
                        .enum(['sum', 'avg', 'count', 'min', 'max', 'p95', 'rate', 'increase', 'histogram_quantile'])
                        .describe(
                            '\* `sum` - sum\n\* `avg` - avg\n\* `count` - count\n\* `min` - min\n\* `max` - max\n\* `p95` - p95\n\* `rate` - rate\n\* `increase` - increase\n\* `histogram_quantile` - histogram_quantile'
                        ),
                    zod.null(),
                ])
                .optional()
                .describe(
                    "Aggregation to characterize. Omit to auto-pick from the metric's OTel type (counter -> rate, gauge -> avg, histogram -> histogram_quantile 0.95).\n\n\* `sum` - sum\n\* `avg` - avg\n\* `count` - count\n\* `min` - min\n\* `max` - max\n\* `p95` - p95\n\* `rate` - rate\n\* `increase` - increase\n\* `histogram_quantile` - histogram_quantile"
                ),
            quantile: zod
                .number()
                .min(metricsCharacterizeCreateBodyQueryOneQuantileMin)
                .max(metricsCharacterizeCreateBodyQueryOneQuantileMax)
                .nullish()
                .describe('Quantile for histogram_quantile. Defaults to 0.95.'),
            filters: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .max(metricsCharacterizeCreateBodyQueryOneFiltersItemKeyMax)
                            .describe(
                                "Attribute name to filter on, without any type-tag suffix (e.g. 'k8s.pod.name', 'env')."
                            ),
                        op: zod
                            .enum(['eq', 'neq', 'regex', 'not_regex'])
                            .describe('\* `eq` - eq\n\* `neq` - neq\n\* `regex` - regex\n\* `not_regex` - not_regex')
                            .default(metricsCharacterizeCreateBodyQueryOneFiltersItemOpDefault)
                            .describe(
                                "Comparison operator. 'regex'\/'not_regex' use RE2 syntax. Negative operators also match rows that lack the key entirely, mirroring Prometheus negative matchers.\n\n\* `eq` - eq\n\* `neq` - neq\n\* `regex` - regex\n\* `not_regex` - not_regex"
                            ),
                        value: zod
                            .string()
                            .max(metricsCharacterizeCreateBodyQueryOneFiltersItemValueMax)
                            .describe('Value to compare against. For regex operators this is the pattern.'),
                        scope: zod
                            .enum(['resource', 'attribute', 'auto'])
                            .describe('\* `resource` - resource\n\* `attribute` - attribute\n\* `auto` - auto')
                            .default(metricsCharacterizeCreateBodyQueryOneFiltersItemScopeDefault)
                            .describe(
                                "Where the attribute lives: 'resource' = per-target resource attributes (k8s.pod.name, service.version), 'attribute' = per-datapoint attributes (http.method, path), 'auto' = resource first with per-datapoint fallback. Use 'auto' unless you know the exact scope.\n\n\* `resource` - resource\n\* `attribute` - attribute\n\* `auto` - auto"
                            ),
                    })
                )
                .optional()
                .describe('Label predicates narrowing which series are characterized.'),
            candidateKeys: zod
                .array(zod.string().max(metricsCharacterizeCreateBodyQueryOneCandidateKeysItemMax))
                .optional()
                .describe(
                    'Label keys to drill into when finding which label values moved. Omit to auto-discover the most common keys on this metric (plus service_name). Max 4 are used.'
                ),
        })
        .describe('The anomaly characterization to run.'),
})

/**
 * Check dashboard panel queries before they go on a dashboard: the metrics must exist, PromQL must
 * run, and SQL must compile and read only logs or traces.
 */
export const MetricsDashboardImportsValidateCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const metricsDashboardImportsValidateCreateBodyPanelsItemKeyMax = 64

export const metricsDashboardImportsValidateCreateBodyPanelsItemBuilderOneClausesItemNameMax = 64

export const metricsDashboardImportsValidateCreateBodyPanelsItemBuilderOneClausesItemMetricNameMax = 255

export const metricsDashboardImportsValidateCreateBodyPanelsItemBuilderOneClausesItemQuantileMin = 0
export const metricsDashboardImportsValidateCreateBodyPanelsItemBuilderOneClausesItemQuantileMax = 1

export const metricsDashboardImportsValidateCreateBodyPanelsItemBuilderOneClausesItemFiltersItemKeyMax = 255

export const metricsDashboardImportsValidateCreateBodyPanelsItemBuilderOneClausesItemFiltersItemValueMax = 1024

export const metricsDashboardImportsValidateCreateBodyPanelsItemBuilderOneClausesItemGroupByItemMax = 255

export const metricsDashboardImportsValidateCreateBodyPanelsMax = 20

export const MetricsDashboardImportsValidateCreateBody = () => zod.object({
    panels: zod
        .array(
            zod.object({
                key: zod
                    .string()
                    .max(metricsDashboardImportsValidateCreateBodyPanelsItemKeyMax)
                    .describe('Panel key. The result for the panel carries the same key.'),
                language: zod
                    .enum(['promql', 'builder', 'histogram', 'hogql'])
                    .describe(
                        '\* `promql` - Promql\n\* `builder` - Builder\n\* `histogram` - Histogram\n\* `hogql` - Hogql'
                    )
                    .describe(
                        "'promql' or 'builder' for metrics, 'histogram' for a latency heatmap, 'hogql' for logs and traces.\n\n\* `promql` - Promql\n\* `builder` - Builder\n\* `histogram` - Histogram\n\* `hogql` - Hogql"
                    ),
                promql: zod.string().nullish().describe("PromQL expression. Used when language is 'promql'."),
                builder: zod
                    .union([
                        zod.object({
                            clauses: zod
                                .array(
                                    zod.object({
                                        name: zod
                                            .string()
                                            .max(
                                                metricsDashboardImportsValidateCreateBodyPanelsItemBuilderOneClausesItemNameMax
                                            )
                                            .describe("Alias that a formula uses, for example 'a'."),
                                        metric_name: zod
                                            .string()
                                            .max(
                                                metricsDashboardImportsValidateCreateBodyPanelsItemBuilderOneClausesItemMetricNameMax
                                            )
                                            .describe('Exact metric name.'),
                                        aggregation: zod
                                            .enum([
                                                'sum',
                                                'avg',
                                                'count',
                                                'min',
                                                'max',
                                                'p95',
                                                'rate',
                                                'increase',
                                                'histogram_quantile',
                                            ])
                                            .describe(
                                                '\* `sum` - sum\n\* `avg` - avg\n\* `count` - count\n\* `min` - min\n\* `max` - max\n\* `p95` - p95\n\* `rate` - rate\n\* `increase` - increase\n\* `histogram_quantile` - histogram_quantile'
                                            )
                                            .describe(
                                                'Aggregation for each bucket, with the same meaning as in the metrics query API.\n\n\* `sum` - sum\n\* `avg` - avg\n\* `count` - count\n\* `min` - min\n\* `max` - max\n\* `p95` - p95\n\* `rate` - rate\n\* `increase` - increase\n\* `histogram_quantile` - histogram_quantile'
                                            ),
                                        quantile: zod
                                            .number()
                                            .min(
                                                metricsDashboardImportsValidateCreateBodyPanelsItemBuilderOneClausesItemQuantileMin
                                            )
                                            .max(
                                                metricsDashboardImportsValidateCreateBodyPanelsItemBuilderOneClausesItemQuantileMax
                                            )
                                            .nullish()
                                            .describe(
                                                "Quantile between 0 and 1. Required for 'histogram_quantile'. The other aggregations ignore it."
                                            ),
                                        filters: zod
                                            .array(
                                                zod.object({
                                                    key: zod
                                                        .string()
                                                        .max(
                                                            metricsDashboardImportsValidateCreateBodyPanelsItemBuilderOneClausesItemFiltersItemKeyMax
                                                        )
                                                        .describe("Attribute name, for example 'service.name'."),
                                                    op: zod
                                                        .enum(['eq', 'neq', 'regex', 'not_regex'])
                                                        .describe(
                                                            '\* `eq` - eq\n\* `neq` - neq\n\* `regex` - regex\n\* `not_regex` - not_regex'
                                                        )
                                                        .describe(
                                                            'Comparison. Regex operators use RE2.\n\n\* `eq` - eq\n\* `neq` - neq\n\* `regex` - regex\n\* `not_regex` - not_regex'
                                                        ),
                                                    value: zod
                                                        .string()
                                                        .max(
                                                            metricsDashboardImportsValidateCreateBodyPanelsItemBuilderOneClausesItemFiltersItemValueMax
                                                        )
                                                        .describe('Value or regex to compare against.'),
                                                })
                                            )
                                            .optional()
                                            .describe('Attribute filters, joined with AND.'),
                                        group_by: zod
                                            .array(
                                                zod
                                                    .string()
                                                    .max(
                                                        metricsDashboardImportsValidateCreateBodyPanelsItemBuilderOneClausesItemGroupByItemMax
                                                    )
                                            )
                                            .optional()
                                            .describe('Attribute names that split the result into series.'),
                                    })
                                )
                                .describe('One clause for each series.'),
                            formula: zod
                                .string()
                                .nullish()
                                .describe("Arithmetic over clause aliases, for example 'a \/ b'."),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe("Builder query. Used when language is 'builder'."),
                histogram_metric: zod
                    .string()
                    .nullish()
                    .describe("Histogram metric name. Used when language is 'histogram'."),
                hogql: zod
                    .string()
                    .nullish()
                    .describe(
                        "SQL SELECT over logs or posthog.trace_spans with {filters} in the WHERE clause. Used when language is 'hogql'."
                    ),
            })
        )
        .min(1)
        .max(metricsDashboardImportsValidateCreateBodyPanelsMax)
        .describe('Up to 20 panel queries to check.'),
})

export const MetricsQueryCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const metricsQueryCreateBodyQueryOneMetricNameMax = 255

export const metricsQueryCreateBodyQueryOneAggregationDefault = `sum`
export const metricsQueryCreateBodyQueryOneQuantileMin = 0
export const metricsQueryCreateBodyQueryOneQuantileMax = 1

export const metricsQueryCreateBodyQueryOneFiltersItemKeyMax = 255

export const metricsQueryCreateBodyQueryOneFiltersItemOpDefault = `eq`
export const metricsQueryCreateBodyQueryOneFiltersItemValueMax = 1024

export const metricsQueryCreateBodyQueryOneFiltersItemScopeDefault = `auto`
export const metricsQueryCreateBodyQueryOneGroupByItemKeyMax = 255

export const metricsQueryCreateBodyQueryOneGroupByItemScopeDefault = `auto`
export const metricsQueryCreateBodyQueryOneClausesItemNameMax = 64

export const metricsQueryCreateBodyQueryOneClausesItemMetricNameMax = 255

export const metricsQueryCreateBodyQueryOneClausesItemAggregationDefault = `sum`
export const metricsQueryCreateBodyQueryOneClausesItemQuantileMin = 0
export const metricsQueryCreateBodyQueryOneClausesItemQuantileMax = 1

export const metricsQueryCreateBodyQueryOneClausesItemFiltersItemKeyMax = 255

export const metricsQueryCreateBodyQueryOneClausesItemFiltersItemOpDefault = `eq`
export const metricsQueryCreateBodyQueryOneClausesItemFiltersItemValueMax = 1024

export const metricsQueryCreateBodyQueryOneClausesItemFiltersItemScopeDefault = `auto`
export const metricsQueryCreateBodyQueryOneClausesItemGroupByItemKeyMax = 255

export const metricsQueryCreateBodyQueryOneClausesItemGroupByItemScopeDefault = `auto`
export const metricsQueryCreateBodyQueryOneFormulaMax = 512

export const MetricsQueryCreateBody = () => zod.object({
    query: zod
        .object({
            metricName: zod
                .string()
                .max(metricsQueryCreateBodyQueryOneMetricNameMax)
                .optional()
                .describe(
                    "Exact metric name to query (e.g. 'http.server.duration'). Single-clause shorthand — mutually exclusive with 'clauses'."
                ),
            metricType: zod
                .union([
                    zod
                        .enum(['gauge', 'sum', 'histogram', 'exponential_histogram', 'summary'])
                        .describe(
                            '\* `gauge` - gauge\n\* `sum` - sum\n\* `histogram` - histogram\n\* `exponential_histogram` - exponential_histogram\n\* `summary` - summary'
                        ),
                    zod.null(),
                ])
                .optional()
                .describe(
                    "Constrain the query to one metric type. A name can exist as several types (e.g. a counter and a gauge); without this, rows of every type sharing the name are blended into one aggregate. Get the type from 'metric-names-list'.\n\n\* `gauge` - gauge\n\* `sum` - sum\n\* `histogram` - histogram\n\* `exponential_histogram` - exponential_histogram\n\* `summary` - summary"
                ),
            aggregation: zod
                .enum(['sum', 'avg', 'count', 'min', 'max', 'p95', 'rate', 'increase', 'histogram_quantile'])
                .describe(
                    '\* `sum` - sum\n\* `avg` - avg\n\* `count` - count\n\* `min` - min\n\* `max` - max\n\* `p95` - p95\n\* `rate` - rate\n\* `increase` - increase\n\* `histogram_quantile` - histogram_quantile'
                )
                .default(metricsQueryCreateBodyQueryOneAggregationDefault)
                .describe(
                    "Aggregation applied per time bucket, always across series rather than across raw samples. 'sum', 'avg', 'min', 'max' and 'p95' reduce each series to its last sample in the bucket and then combine those, so the result does not scale with the scrape rate; 'count' is the number of series that reported. 'rate' (per-second) and 'increase' are counter-aware: per-series deltas with Prometheus counter-reset handling, temporality-aware (delta-temporality samples count as-is). 'histogram_quantile' interpolates from OTel histogram buckets and requires 'quantile'.\n\n\* `sum` - sum\n\* `avg` - avg\n\* `count` - count\n\* `min` - min\n\* `max` - max\n\* `p95` - p95\n\* `rate` - rate\n\* `increase` - increase\n\* `histogram_quantile` - histogram_quantile"
                ),
            quantile: zod
                .number()
                .min(metricsQueryCreateBodyQueryOneQuantileMin)
                .max(metricsQueryCreateBodyQueryOneQuantileMax)
                .nullish()
                .describe("Quantile in (0, 1) for 'histogram_quantile' (e.g. 0.95). Ignored for other aggregations."),
            filters: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .max(metricsQueryCreateBodyQueryOneFiltersItemKeyMax)
                            .describe(
                                "Attribute name to filter on, without any type-tag suffix (e.g. 'k8s.pod.name', 'env')."
                            ),
                        op: zod
                            .enum(['eq', 'neq', 'regex', 'not_regex'])
                            .describe('\* `eq` - eq\n\* `neq` - neq\n\* `regex` - regex\n\* `not_regex` - not_regex')
                            .default(metricsQueryCreateBodyQueryOneFiltersItemOpDefault)
                            .describe(
                                "Comparison operator. 'regex'\/'not_regex' use RE2 syntax. Negative operators also match rows that lack the key entirely, mirroring Prometheus negative matchers.\n\n\* `eq` - eq\n\* `neq` - neq\n\* `regex` - regex\n\* `not_regex` - not_regex"
                            ),
                        value: zod
                            .string()
                            .max(metricsQueryCreateBodyQueryOneFiltersItemValueMax)
                            .describe('Value to compare against. For regex operators this is the pattern.'),
                        scope: zod
                            .enum(['resource', 'attribute', 'auto'])
                            .describe('\* `resource` - resource\n\* `attribute` - attribute\n\* `auto` - auto')
                            .default(metricsQueryCreateBodyQueryOneFiltersItemScopeDefault)
                            .describe(
                                "Where the attribute lives: 'resource' = per-target resource attributes (k8s.pod.name, service.version), 'attribute' = per-datapoint attributes (http.method, path), 'auto' = resource first with per-datapoint fallback. Use 'auto' unless you know the exact scope.\n\n\* `resource` - resource\n\* `attribute` - attribute\n\* `auto` - auto"
                            ),
                    })
                )
                .optional()
                .describe('Label predicates ANDed together. Rows must satisfy every filter.'),
            groupBy: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .max(metricsQueryCreateBodyQueryOneGroupByItemKeyMax)
                            .describe("Attribute name to split series by (e.g. 'k8s.pod.name', 'env')."),
                        scope: zod
                            .enum(['resource', 'attribute', 'auto'])
                            .describe('\* `resource` - resource\n\* `attribute` - attribute\n\* `auto` - auto')
                            .default(metricsQueryCreateBodyQueryOneGroupByItemScopeDefault)
                            .describe(
                                "Where the attribute lives; same semantics as filter scope. Use 'auto' unless you know the exact scope.\n\n\* `resource` - resource\n\* `attribute` - attribute\n\* `auto` - auto"
                            ),
                    })
                )
                .optional()
                .describe(
                    'Labels to split the result into separate series by. Series share one time grid and are capped at the 100 largest.'
                ),
            interval: zod
                .union([
                    zod
                        .enum([
                            'second_15',
                            'second_30',
                            'minute',
                            'minute_5',
                            'minute_15',
                            'minute_30',
                            'hour',
                            'hour_6',
                            'day',
                            'week',
                        ])
                        .describe(
                            '\* `second_15` - second_15\n\* `second_30` - second_30\n\* `minute` - minute\n\* `minute_5` - minute_5\n\* `minute_15` - minute_15\n\* `minute_30` - minute_30\n\* `hour` - hour\n\* `hour_6` - hour_6\n\* `day` - day\n\* `week` - week'
                        ),
                    zod.null(),
                ])
                .optional()
                .describe(
                    'Bucket size for the shared time grid. Omit to auto-pick (~60 buckets across the range).\n\n\* `second_15` - second_15\n\* `second_30` - second_30\n\* `minute` - minute\n\* `minute_5` - minute_5\n\* `minute_15` - minute_15\n\* `minute_30` - minute_30\n\* `hour` - hour\n\* `hour_6` - hour_6\n\* `day` - day\n\* `week` - week'
                ),
            clauses: zod
                .array(
                    zod.object({
                        name: zod
                            .string()
                            .max(metricsQueryCreateBodyQueryOneClausesItemNameMax)
                            .describe("Clause name a formula refers to (e.g. 'a')."),
                        metricName: zod
                            .string()
                            .max(metricsQueryCreateBodyQueryOneClausesItemMetricNameMax)
                            .describe('Exact metric name this clause queries.'),
                        metricType: zod
                            .union([
                                zod
                                    .enum(['gauge', 'sum', 'histogram', 'exponential_histogram', 'summary'])
                                    .describe(
                                        '\* `gauge` - gauge\n\* `sum` - sum\n\* `histogram` - histogram\n\* `exponential_histogram` - exponential_histogram\n\* `summary` - summary'
                                    ),
                                zod.null(),
                            ])
                            .optional()
                            .describe(
                                "Constrain the query to one metric type. A name can exist as several types (e.g. a counter and a gauge); without this, rows of every type sharing the name are blended into one aggregate. Get the type from 'metric-names-list'.\n\n\* `gauge` - gauge\n\* `sum` - sum\n\* `histogram` - histogram\n\* `exponential_histogram` - exponential_histogram\n\* `summary` - summary"
                            ),
                        aggregation: zod
                            .enum([
                                'sum',
                                'avg',
                                'count',
                                'min',
                                'max',
                                'p95',
                                'rate',
                                'increase',
                                'histogram_quantile',
                            ])
                            .describe(
                                '\* `sum` - sum\n\* `avg` - avg\n\* `count` - count\n\* `min` - min\n\* `max` - max\n\* `p95` - p95\n\* `rate` - rate\n\* `increase` - increase\n\* `histogram_quantile` - histogram_quantile'
                            )
                            .default(metricsQueryCreateBodyQueryOneClausesItemAggregationDefault)
                            .describe(
                                'Aggregation applied per time bucket; same semantics as the top-level aggregation.\n\n\* `sum` - sum\n\* `avg` - avg\n\* `count` - count\n\* `min` - min\n\* `max` - max\n\* `p95` - p95\n\* `rate` - rate\n\* `increase` - increase\n\* `histogram_quantile` - histogram_quantile'
                            ),
                        quantile: zod
                            .number()
                            .min(metricsQueryCreateBodyQueryOneClausesItemQuantileMin)
                            .max(metricsQueryCreateBodyQueryOneClausesItemQuantileMax)
                            .nullish()
                            .describe("Quantile in (0, 1) for 'histogram_quantile'."),
                        filters: zod
                            .array(
                                zod.object({
                                    key: zod
                                        .string()
                                        .max(metricsQueryCreateBodyQueryOneClausesItemFiltersItemKeyMax)
                                        .describe(
                                            "Attribute name to filter on, without any type-tag suffix (e.g. 'k8s.pod.name', 'env')."
                                        ),
                                    op: zod
                                        .enum(['eq', 'neq', 'regex', 'not_regex'])
                                        .describe(
                                            '\* `eq` - eq\n\* `neq` - neq\n\* `regex` - regex\n\* `not_regex` - not_regex'
                                        )
                                        .default(metricsQueryCreateBodyQueryOneClausesItemFiltersItemOpDefault)
                                        .describe(
                                            "Comparison operator. 'regex'\/'not_regex' use RE2 syntax. Negative operators also match rows that lack the key entirely, mirroring Prometheus negative matchers.\n\n\* `eq` - eq\n\* `neq` - neq\n\* `regex` - regex\n\* `not_regex` - not_regex"
                                        ),
                                    value: zod
                                        .string()
                                        .max(metricsQueryCreateBodyQueryOneClausesItemFiltersItemValueMax)
                                        .describe('Value to compare against. For regex operators this is the pattern.'),
                                    scope: zod
                                        .enum(['resource', 'attribute', 'auto'])
                                        .describe(
                                            '\* `resource` - resource\n\* `attribute` - attribute\n\* `auto` - auto'
                                        )
                                        .default(metricsQueryCreateBodyQueryOneClausesItemFiltersItemScopeDefault)
                                        .describe(
                                            "Where the attribute lives: 'resource' = per-target resource attributes (k8s.pod.name, service.version), 'attribute' = per-datapoint attributes (http.method, path), 'auto' = resource first with per-datapoint fallback. Use 'auto' unless you know the exact scope.\n\n\* `resource` - resource\n\* `attribute` - attribute\n\* `auto` - auto"
                                        ),
                                })
                            )
                            .optional()
                            .describe('Label predicates ANDed together for this clause.'),
                        groupBy: zod
                            .array(
                                zod.object({
                                    key: zod
                                        .string()
                                        .max(metricsQueryCreateBodyQueryOneClausesItemGroupByItemKeyMax)
                                        .describe("Attribute name to split series by (e.g. 'k8s.pod.name', 'env')."),
                                    scope: zod
                                        .enum(['resource', 'attribute', 'auto'])
                                        .describe(
                                            '\* `resource` - resource\n\* `attribute` - attribute\n\* `auto` - auto'
                                        )
                                        .default(metricsQueryCreateBodyQueryOneClausesItemGroupByItemScopeDefault)
                                        .describe(
                                            "Where the attribute lives; same semantics as filter scope. Use 'auto' unless you know the exact scope.\n\n\* `resource` - resource\n\* `attribute` - attribute\n\* `auto` - auto"
                                        ),
                                })
                            )
                            .optional()
                            .describe('Labels to split this clause into separate series by.'),
                    })
                )
                .optional()
                .describe(
                    "Full multi-clause form: each clause is an independent metric selection sharing the request's time grid (maximum 10). Mutually exclusive with 'metricName'."
                ),
            formula: zod
                .string()
                .max(metricsQueryCreateBodyQueryOneFormulaMax)
                .nullish()
                .describe(
                    "Arithmetic over clause names evaluated server-side per grid point, e.g. '(a - b) \/ a'. Supports + - \* \/ and parentheses; division by zero yields 0. When set, only the formula result series are returned."
                ),
            dateFrom: zod.iso
                .datetime({ offset: true })
                .describe('Lower bound (inclusive) for the query range. ISO 8601.'),
            dateTo: zod.iso
                .datetime({ offset: true })
                .optional()
                .describe('Upper bound (exclusive) for the query range. Defaults to now if omitted.'),
        })
        .describe('The metric query to execute.'),
})

/**
 * Distinct metric names for the team. Backs the catalog UI.
 */
export const MetricsValuesRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const metricsValuesRetrieveQueryLimitDefault = 100
export const metricsValuesRetrieveQueryLimitMax = 1000

export const metricsValuesRetrieveQueryServiceMax = 1024

export const metricsValuesRetrieveQueryValueDefault = ``
export const metricsValuesRetrieveQueryValueMax = 255

export const MetricsValuesRetrieveQueryParams = () => zod.object({
    limit: zod
        .number()
        .min(1)
        .max(metricsValuesRetrieveQueryLimitMax)
        .default(metricsValuesRetrieveQueryLimitDefault)
        .describe('Max number of names to return. Defaults to 100; maximum 1000.'),
    service: zod
        .string()
        .max(metricsValuesRetrieveQueryServiceMax)
        .optional()
        .describe(
            'Comma-separated services to narrow the list to, e.g. `service=web,worker`. Omit for every service. Send it empty to select only series whose sender did not set `service.name`. A service name containing a comma cannot be selected.'
        ),
    value: zod
        .string()
        .max(metricsValuesRetrieveQueryValueMax)
        .default(metricsValuesRetrieveQueryValueDefault)
        .describe('Substring filter (case-insensitive) applied to metric names.'),
})
