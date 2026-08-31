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
 * Take one chart point apart into the series and samples behind it,
 * and recompute it independently so the plotted number can be checked
 * rather than trusted.
 */
export const metricsExplainCreateBodyQueryOneMetricNameMax = 255

export const metricsExplainCreateBodyQueryOneAggregationDefault = `sum`
export const metricsExplainCreateBodyQueryOneQuantileMin = 0
export const metricsExplainCreateBodyQueryOneQuantileMax = 1

export const metricsExplainCreateBodyQueryOneFiltersItemKeyMax = 255

export const metricsExplainCreateBodyQueryOneFiltersItemOpDefault = `eq`
export const metricsExplainCreateBodyQueryOneFiltersItemValueMax = 1024

export const metricsExplainCreateBodyQueryOneFiltersItemScopeDefault = `auto`

export const MetricsExplainCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .object({
            metricName: zod
                .string()
                .max(metricsExplainCreateBodyQueryOneMetricNameMax)
                .describe('Exact metric name whose bucket should be taken apart.'),
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
                    'Constrain the bucket to one metric type. A name can exist as several types; without this, rows of every type sharing the name are decomposed together.\n\n\* `gauge` - gauge\n\* `sum` - sum\n\* `histogram` - histogram\n\* `exponential_histogram` - exponential_histogram\n\* `summary` - summary'
                ),
            aggregation: zod
                .enum(['sum', 'avg', 'count', 'min', 'max', 'p95', 'rate', 'increase', 'histogram_quantile'])
                .describe(
                    '\* `sum` - sum\n\* `avg` - avg\n\* `count` - count\n\* `min` - min\n\* `max` - max\n\* `p95` - p95\n\* `rate` - rate\n\* `increase` - increase\n\* `histogram_quantile` - histogram_quantile'
                )
                .default(metricsExplainCreateBodyQueryOneAggregationDefault)
                .describe(
                    "The aggregation whose result should be explained. 'histogram_quantile' is rejected: it reduces bucket-count arrays rather than scalar samples, so there is no per-series value to lay out.\n\n\* `sum` - sum\n\* `avg` - avg\n\* `count` - count\n\* `min` - min\n\* `max` - max\n\* `p95` - p95\n\* `rate` - rate\n\* `increase` - increase\n\* `histogram_quantile` - histogram_quantile"
                ),
            quantile: zod
                .number()
                .min(metricsExplainCreateBodyQueryOneQuantileMin)
                .max(metricsExplainCreateBodyQueryOneQuantileMax)
                .nullish()
                .describe("Quantile in (0, 1) applied across series. Defaults to 0.95 for the 'p95' aggregation."),
            filters: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .max(metricsExplainCreateBodyQueryOneFiltersItemKeyMax)
                            .describe(
                                "Attribute name to filter on, without any type-tag suffix (e.g. 'k8s.pod.name', 'env')."
                            ),
                        op: zod
                            .enum(['eq', 'neq', 'regex', 'not_regex'])
                            .describe('\* `eq` - eq\n\* `neq` - neq\n\* `regex` - regex\n\* `not_regex` - not_regex')
                            .default(metricsExplainCreateBodyQueryOneFiltersItemOpDefault)
                            .describe(
                                "Comparison operator. 'regex'\/'not_regex' use RE2 syntax. Negative operators also match rows that lack the key entirely, mirroring Prometheus negative matchers.\n\n\* `eq` - eq\n\* `neq` - neq\n\* `regex` - regex\n\* `not_regex` - not_regex"
                            ),
                        value: zod
                            .string()
                            .max(metricsExplainCreateBodyQueryOneFiltersItemValueMax)
                            .describe('Value to compare against. For regex operators this is the pattern.'),
                        scope: zod
                            .enum(['resource', 'attribute', 'auto'])
                            .describe('\* `resource` - resource\n\* `attribute` - attribute\n\* `auto` - auto')
                            .default(metricsExplainCreateBodyQueryOneFiltersItemScopeDefault)
                            .describe(
                                "Where the attribute lives: 'resource' = per-target resource attributes (k8s.pod.name, service.version), 'attribute' = per-datapoint attributes (http.method, path), 'auto' = resource first with per-datapoint fallback. Use 'auto' unless you know the exact scope.\n\n\* `resource` - resource\n\* `attribute` - attribute\n\* `auto` - auto"
                            ),
                    })
                )
                .optional()
                .describe('Label predicates ANDed together, matching the chart the point came from.'),
            bucketStart: zod.iso
                .datetime({ offset: true })
                .describe("Start of the bucket to explain, as returned in a query result's 'time'. ISO 8601."),
            interval: zod
                .enum(['second', 'minute', 'minute_5', 'minute_15', 'hour', 'hour_6', 'day', 'week'])
                .describe(
                    '\* `second` - second\n\* `minute` - minute\n\* `minute_5` - minute_5\n\* `minute_15` - minute_15\n\* `hour` - hour\n\* `hour_6` - hour_6\n\* `day` - day\n\* `week` - week'
                )
                .describe(
                    'Bucket size the point was plotted at. Must match the query that produced it, or the decomposition explains a different span.\n\n\* `second` - second\n\* `minute` - minute\n\* `minute_5` - minute_5\n\* `minute_15` - minute_15\n\* `hour` - hour\n\* `hour_6` - hour_6\n\* `day` - day\n\* `week` - week'
                ),
        })
        .describe('The chart point to take apart.'),
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
                        .enum(['second', 'minute', 'minute_5', 'minute_15', 'hour', 'hour_6', 'day', 'week'])
                        .describe(
                            '\* `second` - second\n\* `minute` - minute\n\* `minute_5` - minute_5\n\* `minute_15` - minute_15\n\* `hour` - hour\n\* `hour_6` - hour_6\n\* `day` - day\n\* `week` - week'
                        ),
                    zod.null(),
                ])
                .optional()
                .describe(
                    'Bucket size for the shared time grid. Omit to auto-pick (~60 buckets across the range).\n\n\* `second` - second\n\* `minute` - minute\n\* `minute_5` - minute_5\n\* `minute_15` - minute_15\n\* `hour` - hour\n\* `hour_6` - hour_6\n\* `day` - day\n\* `week` - week'
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
 * Raw individual emissions for a metric (the events model), newest
 * first — backs the Samples view and the metric->trace pivot.
 */
export const metricsSamplesCreateBodyQueryOneMetricNameMax = 255

export const metricsSamplesCreateBodyQueryOneTraceIdMax = 255

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
                .describe("Exact metric name to list raw emissions for (e.g. 'http.server.duration')."),
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
