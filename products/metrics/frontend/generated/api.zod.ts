/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Characterize a metric anomaly: compare an anomaly window against a
 * baseline, find the onset, and rank which label values moved.
 */
export const metricsCharacterizeCreateBodyQueryOneMetricNameMax = 255

export const metricsCharacterizeCreateBodyQueryOneQuantileMin = 0
export const metricsCharacterizeCreateBodyQueryOneQuantileMax = 1

export const metricsCharacterizeCreateBodyQueryOneFiltersItemKeyMax = 255

export const metricsCharacterizeCreateBodyQueryOneFiltersItemOpDefault = `eq`
export const metricsCharacterizeCreateBodyQueryOneFiltersItemValueMax = 1024

export const metricsCharacterizeCreateBodyQueryOneFiltersItemScopeDefault = `auto`
export const metricsCharacterizeCreateBodyQueryOneCandidateKeysItemMax = 255

export const MetricsCharacterizeCreateBody = /* @__PURE__ */ zod.object({
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
 * Import a Grafana dashboard JSON model or a dashboard screenshot as a new dashboard. Panels that match the project's metrics import at once. An AI agent converts the rest, and the response then has an id to poll.
 */
export const metricsDashboardImportsCreateBodyNameMax = 400

export const metricsDashboardImportsCreateBodyGrafanaJsonMax = 5242880

export const metricsDashboardImportsCreateBodyImageBase64Max = 7340032

export const MetricsDashboardImportsCreateBody = /* @__PURE__ */ zod.object({
    source: zod
        .enum(['grafana', 'screenshot'])
        .describe('\* `grafana` - Grafana\n\* `screenshot` - Screenshot')
        .describe(
            "What to import: 'grafana' reads a Grafana dashboard JSON model, 'screenshot' reads an image of a dashboard.\n\n\* `grafana` - Grafana\n\* `screenshot` - Screenshot"
        ),
    name: zod
        .string()
        .max(metricsDashboardImportsCreateBodyNameMax)
        .optional()
        .describe("Name of the new dashboard. Defaults to the Grafana dashboard title, or to 'Imported dashboard'."),
    grafana_json: zod
        .string()
        .max(metricsDashboardImportsCreateBodyGrafanaJsonMax)
        .optional()
        .describe(
            "The Grafana dashboard JSON model as text, from Dashboard settings > JSON Model or from an export. Required when source is 'grafana'."
        ),
    image_base64: zod
        .string()
        .max(metricsDashboardImportsCreateBodyImageBase64Max)
        .optional()
        .describe(
            "The screenshot as base64, without a data URL prefix. PNG, JPEG, WebP or GIF, at most 5 MB. Required when source is 'screenshot'."
        ),
})

/**
 * Check dashboard panel queries before they go on a dashboard: the metrics must exist, PromQL must
 * run, and SQL must compile and read only logs or traces.
 */
export const metricsDashboardImportsValidateCreateBodyPanelsItemKeyMax = 64

export const metricsDashboardImportsValidateCreateBodyPanelsItemTitleMax = 200

export const metricsDashboardImportsValidateCreateBodyPanelsItemBuilderOneClausesItemNameMax = 64

export const metricsDashboardImportsValidateCreateBodyPanelsItemBuilderOneClausesItemMetricNameMax = 255

export const metricsDashboardImportsValidateCreateBodyPanelsItemBuilderOneClausesItemQuantileMin = 0
export const metricsDashboardImportsValidateCreateBodyPanelsItemBuilderOneClausesItemQuantileMax = 1

export const metricsDashboardImportsValidateCreateBodyPanelsItemBuilderOneClausesItemFiltersItemKeyMax = 255

export const metricsDashboardImportsValidateCreateBodyPanelsItemBuilderOneClausesItemFiltersItemValueMax = 1024

export const metricsDashboardImportsValidateCreateBodyPanelsItemBuilderOneClausesItemGroupByItemMax = 255

export const metricsDashboardImportsValidateCreateBodyPanelsMax = 20

export const MetricsDashboardImportsValidateCreateBody = /* @__PURE__ */ zod.object({
    panels: zod
        .array(
            zod.object({
                key: zod
                    .string()
                    .max(metricsDashboardImportsValidateCreateBodyPanelsItemKeyMax)
                    .describe('Panel key. The result for the panel carries the same key.'),
                title: zod
                    .string()
                    .max(metricsDashboardImportsValidateCreateBodyPanelsItemTitleMax)
                    .optional()
                    .describe('Panel title, shown in the import progress.'),
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
                                                '\* `sum` - Sum\n\* `avg` - Avg\n\* `count` - Count\n\* `min` - Min\n\* `max` - Max\n\* `p95` - P95\n\* `rate` - Rate\n\* `increase` - Increase\n\* `histogram_quantile` - Histogram Quantile'
                                            )
                                            .describe(
                                                'Aggregation for each bucket, with the same meaning as in the metrics query API.\n\n\* `sum` - Sum\n\* `avg` - Avg\n\* `count` - Count\n\* `min` - Min\n\* `max` - Max\n\* `p95` - P95\n\* `rate` - Rate\n\* `increase` - Increase\n\* `histogram_quantile` - Histogram Quantile'
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
    import_id: zod
        .uuid()
        .nullish()
        .describe(
            'The import that these panels belong to, from the import instructions. The import progress shows which panels pass.'
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

export const MetricsQueryCreateBody = /* @__PURE__ */ zod.object({
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
                .enum(['none', 'sum', 'avg', 'count', 'min', 'max', 'p95', 'rate', 'increase', 'histogram_quantile'])
                .describe(
                    '\* `none` - none\n\* `sum` - sum\n\* `avg` - avg\n\* `count` - count\n\* `min` - min\n\* `max` - max\n\* `p95` - p95\n\* `rate` - rate\n\* `increase` - increase\n\* `histogram_quantile` - histogram_quantile'
                )
                .default(metricsQueryCreateBodyQueryOneAggregationDefault)
                .describe(
                    "Aggregation applied per time bucket, always across series rather than across raw samples. 'sum', 'avg', 'min', 'max' and 'p95' reduce each series to its last sample in the bucket and then combine those, so the result does not scale with the scrape rate; 'count' is the number of series that reported. 'rate' (per-second) and 'increase' are counter-aware: per-series deltas with Prometheus counter-reset handling, temporality-aware (delta-temporality samples count as-is). 'histogram_quantile' interpolates from OTel histogram buckets and requires 'quantile'. 'none' skips the aggregation and returns one series per label set, at most 100, using each series' last sample per bucket; it cannot be combined with 'groupBy'.\n\n\* `none` - none\n\* `sum` - sum\n\* `avg` - avg\n\* `count` - count\n\* `min` - min\n\* `max` - max\n\* `p95` - p95\n\* `rate` - rate\n\* `increase` - increase\n\* `histogram_quantile` - histogram_quantile"
                ),
            rangeFunction: zod
                .union([
                    zod.enum(['rate', 'increase']).describe('\* `rate` - rate\n\* `increase` - increase'),
                    zod.null(),
                ])
                .optional()
                .describe(
                    "Counter-aware transform applied to each series before the aggregation: 'rate' (per-second) or 'increase'. Combine with 'none' to get one rate line per series. Do not combine with the 'rate' or 'increase' aggregations.\n\n\* `rate` - rate\n\* `increase` - increase"
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
                                'none',
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
                                '\* `none` - none\n\* `sum` - sum\n\* `avg` - avg\n\* `count` - count\n\* `min` - min\n\* `max` - max\n\* `p95` - p95\n\* `rate` - rate\n\* `increase` - increase\n\* `histogram_quantile` - histogram_quantile'
                            )
                            .default(metricsQueryCreateBodyQueryOneClausesItemAggregationDefault)
                            .describe(
                                'Aggregation applied per time bucket; same semantics as the top-level aggregation.\n\n\* `none` - none\n\* `sum` - sum\n\* `avg` - avg\n\* `count` - count\n\* `min` - min\n\* `max` - max\n\* `p95` - p95\n\* `rate` - rate\n\* `increase` - increase\n\* `histogram_quantile` - histogram_quantile'
                            ),
                        rangeFunction: zod
                            .union([
                                zod.enum(['rate', 'increase']).describe('\* `rate` - rate\n\* `increase` - increase'),
                                zod.null(),
                            ])
                            .optional()
                            .describe(
                                "Counter-aware transform applied to each series before the aggregation: 'rate' (per-second) or 'increase'. Combine with 'none' to get one rate line per series. Do not combine with the 'rate' or 'increase' aggregations.\n\n\* `rate` - rate\n\* `increase` - increase"
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
            dateFrom: zod
                .string()
                .optional()
                .describe(
                    "Lower bound (inclusive) for the query range. ISO 8601, or a relative offset back from now such as '-1h', '-7d', '-2w', '-1m' (months). Defaults to 24 hours before dateTo."
                ),
            dateTo: zod
                .string()
                .optional()
                .describe(
                    'Upper bound (exclusive) for the query range. ISO 8601 or a relative offset like dateFrom. Defaults to now if omitted.'
                ),
        })
        .describe('The metric query to execute.'),
})

/**
 * Raw individual emissions for a metric (the events model), newest
 * first — backs the Samples view and the metric->trace pivot.
 */
export const metricsSamplesCreateBodyQueryOneMetricNameMax = 255

export const metricsSamplesCreateBodyQueryOneTraceIdMax = 255

export const metricsSamplesCreateBodyQueryOneSpanIdMax = 255

export const metricsSamplesCreateBodyQueryOneFiltersItemKeyMax = 255

export const metricsSamplesCreateBodyQueryOneFiltersItemOpDefault = `eq`
export const metricsSamplesCreateBodyQueryOneFiltersItemValueMax = 1024

export const metricsSamplesCreateBodyQueryOneFiltersItemScopeDefault = `auto`
export const metricsSamplesCreateBodyQueryOneLimitDefault = 100
export const metricsSamplesCreateBodyQueryOneLimitMax = 1000

export const MetricsSamplesCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .object({
            metricName: zod
                .string()
                .max(metricsSamplesCreateBodyQueryOneMetricNameMax)
                .optional()
                .describe(
                    "Exact metric name to list raw emissions for (e.g. 'http.server.duration'). Omit to list emissions across all metric names — allowed only with traceId (the trace->metrics pivot)."
                ),
            dateFrom: zod.iso
                .datetime({ offset: true })
                .describe('Lower bound (inclusive) for the sample window. ISO 8601.'),
            dateTo: zod.iso
                .datetime({ offset: true })
                .optional()
                .describe('Upper bound (exclusive) for the sample window. Defaults to now if omitted.'),
            traceId: zod
                .string()
                .max(metricsSamplesCreateBodyQueryOneTraceIdMax)
                .optional()
                .describe(
                    'Restrict to emissions on this trace (hex trace id, as the tracing product uses) — the reverse metric->trace pivot. Omit for all traces.'
                ),
            spanId: zod
                .string()
                .max(metricsSamplesCreateBodyQueryOneSpanIdMax)
                .optional()
                .describe(
                    'Restrict to emissions recorded on this span (hex span id). Requires traceId, since a span id is only unique within its trace.'
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
                    'Constrain the emissions to one metric type. A name can exist as several types (e.g. a counter and a gauge); without this, emissions of every type sharing the name are listed together. Pass the same value used for the chart so both describe the same series.\n\n\* `gauge` - gauge\n\* `sum` - sum\n\* `histogram` - histogram\n\* `exponential_histogram` - exponential_histogram\n\* `summary` - summary'
                ),
            filters: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .max(metricsSamplesCreateBodyQueryOneFiltersItemKeyMax)
                            .describe(
                                "Attribute name to filter on, without any type-tag suffix (e.g. 'k8s.pod.name', 'env')."
                            ),
                        op: zod
                            .enum(['eq', 'neq', 'regex', 'not_regex'])
                            .describe('\* `eq` - eq\n\* `neq` - neq\n\* `regex` - regex\n\* `not_regex` - not_regex')
                            .default(metricsSamplesCreateBodyQueryOneFiltersItemOpDefault)
                            .describe(
                                "Comparison operator. 'regex'\/'not_regex' use RE2 syntax. Negative operators also match rows that lack the key entirely, mirroring Prometheus negative matchers.\n\n\* `eq` - eq\n\* `neq` - neq\n\* `regex` - regex\n\* `not_regex` - not_regex"
                            ),
                        value: zod
                            .string()
                            .max(metricsSamplesCreateBodyQueryOneFiltersItemValueMax)
                            .describe('Value to compare against. For regex operators this is the pattern.'),
                        scope: zod
                            .enum(['resource', 'attribute', 'auto'])
                            .describe('\* `resource` - resource\n\* `attribute` - attribute\n\* `auto` - auto')
                            .default(metricsSamplesCreateBodyQueryOneFiltersItemScopeDefault)
                            .describe(
                                "Where the attribute lives: 'resource' = per-target resource attributes (k8s.pod.name, service.version), 'attribute' = per-datapoint attributes (http.method, path), 'auto' = resource first with per-datapoint fallback. Use 'auto' unless you know the exact scope.\n\n\* `resource` - resource\n\* `attribute` - attribute\n\* `auto` - auto"
                            ),
                    })
                )
                .optional()
                .describe(
                    "Label predicates ANDed together, matched against each emission's series. Pass the same filters used for the chart so the emissions listed are the ones behind it."
                ),
            limit: zod
                .number()
                .min(1)
                .max(metricsSamplesCreateBodyQueryOneLimitMax)
                .default(metricsSamplesCreateBodyQueryOneLimitDefault)
                .describe('Max emissions to return, newest first. Defaults to 100, capped at 1000.'),
        })
        .describe('The raw-emissions query to execute.'),
})

/**
 * Distinct metric names for the team. Backs the catalog UI.
 */
export const metricsValuesCreateBodyValueDefault = ``
export const metricsValuesCreateBodyValueMax = 255

export const metricsValuesCreateBodyLimitDefault = 100
export const metricsValuesCreateBodyLimitMax = 1000

export const metricsValuesCreateBodyServiceMax = 1024

export const metricsValuesCreateBodyNamesItemMax = 255

export const metricsValuesCreateBodyNamesMax = 20

export const MetricsValuesCreateBody = /* @__PURE__ */ zod.object({
    value: zod
        .string()
        .max(metricsValuesCreateBodyValueMax)
        .default(metricsValuesCreateBodyValueDefault)
        .describe('Substring filter (case-insensitive) applied to metric names.'),
    limit: zod
        .number()
        .min(1)
        .max(metricsValuesCreateBodyLimitMax)
        .default(metricsValuesCreateBodyLimitDefault)
        .describe('Max number of names to return. Defaults to 100; maximum 1000.'),
    service: zod
        .string()
        .max(metricsValuesCreateBodyServiceMax)
        .optional()
        .describe(
            'Comma-separated services to narrow the list to, e.g. `service=web,worker`. Omit for every service. Send it empty to select only series whose sender did not set `service.name`. A service name containing a comma cannot be selected.'
        ),
    names: zod
        .array(zod.string().max(metricsValuesCreateBodyNamesItemMax))
        .min(1)
        .max(metricsValuesCreateBodyNamesMax)
        .describe('Exact metric names to load as a batch. Overrides value and limit.'),
})

/**
 * The options of one dashboard variable, for the variable selects on dashboards.
 */
export const metricsVariableOptionsCreateBodyQueryMax = 10000

export const metricsVariableOptionsCreateBodyCustomValuesItemMax = 1024

export const metricsVariableOptionsCreateBodyCustomValuesMax = 1000

export const metricsVariableOptionsCreateBodyRegexMax = 1024

export const metricsVariableOptionsCreateBodyVariablesItemNameMax = 128

export const metricsVariableOptionsCreateBodyVariablesItemNameRegExp = new RegExp('^[A-Za-z_][A-Za-z0-9_]\*$')
export const metricsVariableOptionsCreateBodyVariablesItemValuesItemMax = 1024

export const metricsVariableOptionsCreateBodyVariablesItemValuesMax = 1000

export const metricsVariableOptionsCreateBodyVariablesItemAllDefault = false
export const metricsVariableOptionsCreateBodyVariablesItemAllValueMax = 1024

export const metricsVariableOptionsCreateBodyDateFromMax = 64

export const metricsVariableOptionsCreateBodyDateToMax = 64

export const MetricsVariableOptionsCreateBody = /* @__PURE__ */ zod.object({
    source: zod
        .enum(['custom', 'promql', 'sql', 'textbox'])
        .describe('\* `custom` - custom\n\* `promql` - promql\n\* `sql` - sql\n\* `textbox` - textbox')
        .describe(
            'Where the options come from: a static list, a PromQL query, a SQL query, or free text.\n\n\* `custom` - custom\n\* `promql` - promql\n\* `sql` - sql\n\* `textbox` - textbox'
        ),
    query: zod
        .string()
        .max(metricsVariableOptionsCreateBodyQueryMax)
        .nullish()
        .describe(
            'The options query when `source` is `promql` or `sql`. It can refer to other variables as `$name`. PromQL supports label_values(label), label_values(selector, label), label_names(), metrics(regex) and query_result(expr). SQL returns the options in its first column.'
        ),
    customValues: zod
        .array(zod.string().max(metricsVariableOptionsCreateBodyCustomValuesItemMax))
        .max(metricsVariableOptionsCreateBodyCustomValuesMax)
        .nullish()
        .describe('The options when `source` is `custom`.'),
    regex: zod
        .string()
        .max(metricsVariableOptionsCreateBodyRegexMax)
        .nullish()
        .describe(
            'A regex that filters the options of a query, as `pattern` or `\/pattern\/flags`. With a capture group, each option is its first group. An invalid regex is rejected before any query runs.'
        ),
    variables: zod
        .array(
            zod.object({
                name: zod
                    .string()
                    .max(metricsVariableOptionsCreateBodyVariablesItemNameMax)
                    .regex(metricsVariableOptionsCreateBodyVariablesItemNameRegExp)
                    .describe('Variable name. Queries refer to it as `$name`.'),
                values: zod
                    .array(zod.string().max(metricsVariableOptionsCreateBodyVariablesItemValuesItemMax))
                    .max(metricsVariableOptionsCreateBodyVariablesItemValuesMax)
                    .describe('The selected values. When `all` is true, the options that All stands for.'),
                all: zod
                    .boolean()
                    .default(metricsVariableOptionsCreateBodyVariablesItemAllDefault)
                    .describe('True when the variable is set to All.'),
                allValue: zod
                    .string()
                    .max(metricsVariableOptionsCreateBodyVariablesItemAllValueMax)
                    .nullish()
                    .describe('The text that All puts in a PromQL query. `.\*` when it is empty.'),
            })
        )
        .optional()
        .describe('The current selection of the other dashboard variables that the query can refer to.'),
    dateFrom: zod
        .string()
        .max(metricsVariableOptionsCreateBodyDateFromMax)
        .nullish()
        .describe(
            "Start of the window that options come from, as in a dashboard date filter: ISO 8601 or a relative date such as '-7d'. Defaults to 24 hours ago."
        ),
    dateTo: zod
        .string()
        .max(metricsVariableOptionsCreateBodyDateToMax)
        .nullish()
        .describe('End of the window that options come from, in the same format as dateFrom. Defaults to now.'),
})

/**
 * Add a notification destination to a metrics alert. It hears the transitions in `event_kinds`. A PagerDuty destination opens an incident when the alert fires and resolves it when the alert resolves.
 */
export const metricsAlertsDestinationsCreateBodyPagerdutySeverityDefault = `critical`
export const metricsAlertsDestinationsCreateBodyPagerdutyRegionDefault = `us`

export const MetricsAlertsDestinationsCreateBody = /* @__PURE__ */ zod.object({
    type: zod
        .enum(['slack', 'webhook', 'teams', 'discord', 'pagerduty'])
        .describe(
            '\* `slack` - Slack\n\* `webhook` - Webhook\n\* `teams` - Microsoft Teams\n\* `discord` - Discord\n\* `pagerduty` - PagerDuty'
        )
        .describe(
            'Notification destination type.\n\n\* `slack` - Slack\n\* `webhook` - Webhook\n\* `teams` - Microsoft Teams\n\* `discord` - Discord\n\* `pagerduty` - PagerDuty'
        ),
    slack_workspace_id: zod
        .number()
        .optional()
        .describe('Integration ID for the Slack workspace. Required when type=slack.'),
    slack_channel_id: zod.string().optional().describe('Slack channel ID. Required when type=slack.'),
    slack_channel_name: zod.string().optional().describe('Human-readable channel name for display.'),
    webhook_url: zod.url().optional().describe('HTTPS endpoint to post to. Required for webhook, teams and discord.'),
    pagerduty_routing_key: zod
        .string()
        .optional()
        .describe('Integration key of a PagerDuty Events API v2 integration. Required when type=pagerduty.'),
    pagerduty_severity: zod
        .enum(['critical', 'error', 'warning', 'info'])
        .describe('\* `critical` - critical\n\* `error` - error\n\* `warning` - warning\n\* `info` - info')
        .default(metricsAlertsDestinationsCreateBodyPagerdutySeverityDefault)
        .describe(
            'Severity PagerDuty records on the incident. Used when type=pagerduty.\n\n\* `critical` - critical\n\* `error` - error\n\* `warning` - warning\n\* `info` - info'
        ),
    pagerduty_region: zod
        .enum(['us', 'eu'])
        .describe('\* `us` - us\n\* `eu` - eu')
        .default(metricsAlertsDestinationsCreateBodyPagerdutyRegionDefault)
        .describe('PagerDuty service region of the account. Used when type=pagerduty.\n\n\* `us` - us\n\* `eu` - eu'),
    event_kinds: zod
        .array(
            zod
                .enum(['firing', 'resolved', 'errored', 'broken'])
                .describe(
                    '\* `firing` - firing\n\* `resolved` - resolved\n\* `errored` - errored\n\* `broken` - broken'
                )
        )
        .min(1)
        .optional()
        .describe(
            "The alert transitions to send about. Defaults to every kind, or to firing and resolved for PagerDuty, which then hears each incident's trigger and resolve."
        ),
})

/**
 * Delete notification destinations of a metrics alert.
 */
export const metricsAlertsDestinationsDeleteCreateBodyDestinationIdsMax = 100

export const MetricsAlertsDestinationsDeleteCreateBody = /* @__PURE__ */ zod.object({
    destination_ids: zod
        .array(zod.uuid())
        .min(1)
        .max(metricsAlertsDestinationsDeleteCreateBodyDestinationIdsMax)
        .describe('IDs of the destinations to delete, as the list endpoint returns them.'),
})
