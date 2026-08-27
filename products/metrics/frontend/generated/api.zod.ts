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
                        .enum(['sum', 'avg', 'count', 'p95', 'rate', 'increase', 'histogram_quantile'])
                        .describe(
                            '\* `sum` - sum\n\* `avg` - avg\n\* `count` - count\n\* `p95` - p95\n\* `rate` - rate\n\* `increase` - increase\n\* `histogram_quantile` - histogram_quantile'
                        ),
                    zod.null(),
                ])
                .optional()
                .describe(
                    "Aggregation to characterize. Omit to auto-pick from the metric's OTel type (counter -> rate, gauge -> avg, histogram -> histogram_quantile 0.95).\n\n\* `sum` - sum\n\* `avg` - avg\n\* `count` - count\n\* `p95` - p95\n\* `rate` - rate\n\* `increase` - increase\n\* `histogram_quantile` - histogram_quantile"
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
                .enum(['sum', 'avg', 'count', 'p95', 'rate', 'increase', 'histogram_quantile'])
                .describe(
                    '\* `sum` - sum\n\* `avg` - avg\n\* `count` - count\n\* `p95` - p95\n\* `rate` - rate\n\* `increase` - increase\n\* `histogram_quantile` - histogram_quantile'
                )
                .default(metricsExplainCreateBodyQueryOneAggregationDefault)
                .describe(
                    "The aggregation whose result should be explained. 'histogram_quantile' is rejected: it reduces bucket-count arrays rather than scalar samples, so there is no per-series value to lay out.\n\n\* `sum` - sum\n\* `avg` - avg\n\* `count` - count\n\* `p95` - p95\n\* `rate` - rate\n\* `increase` - increase\n\* `histogram_quantile` - histogram_quantile"
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
                .enum(['sum', 'avg', 'count', 'p95', 'rate', 'increase', 'histogram_quantile'])
                .describe(
                    '\* `sum` - sum\n\* `avg` - avg\n\* `count` - count\n\* `p95` - p95\n\* `rate` - rate\n\* `increase` - increase\n\* `histogram_quantile` - histogram_quantile'
                )
                .default(metricsQueryCreateBodyQueryOneAggregationDefault)
                .describe(
                    "Aggregation applied per time bucket, always across series rather than across raw samples. 'sum', 'avg' and 'p95' reduce each series to its last sample in the bucket and then combine those, so the result does not scale with the scrape rate; 'count' is the number of series that reported. 'rate' (per-second) and 'increase' are counter-aware: per-series deltas with Prometheus counter-reset handling, temporality-aware (delta-temporality samples count as-is). 'histogram_quantile' interpolates from OTel histogram buckets and requires 'quantile'.\n\n\* `sum` - sum\n\* `avg` - avg\n\* `count` - count\n\* `p95` - p95\n\* `rate` - rate\n\* `increase` - increase\n\* `histogram_quantile` - histogram_quantile"
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
                            .enum(['sum', 'avg', 'count', 'p95', 'rate', 'increase', 'histogram_quantile'])
                            .describe(
                                '\* `sum` - sum\n\* `avg` - avg\n\* `count` - count\n\* `p95` - p95\n\* `rate` - rate\n\* `increase` - increase\n\* `histogram_quantile` - histogram_quantile'
                            )
                            .default(metricsQueryCreateBodyQueryOneClausesItemAggregationDefault)
                            .describe(
                                'Aggregation applied per time bucket; same semantics as the top-level aggregation.\n\n\* `sum` - sum\n\* `avg` - avg\n\* `count` - count\n\* `p95` - p95\n\* `rate` - rate\n\* `increase` - increase\n\* `histogram_quantile` - histogram_quantile'
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

/**
 * Create a pipeline from a validated topology config.
 */
export const metricsPipelinesCreateBodyNameMax = 400

export const metricsPipelinesCreateBodyDescriptionDefault = ``
export const metricsPipelinesCreateBodyConfigOneNodesItemIdMax = 64

export const metricsPipelinesCreateBodyConfigOneNodesItemNameMax = 120

export const metricsPipelinesCreateBodyConfigOneNodesItemKindDefault = ``
export const metricsPipelinesCreateBodyConfigOneNodesItemKindMax = 120

export const metricsPipelinesCreateBodyConfigOneNodesItemStatsItemIdMax = 64

export const metricsPipelinesCreateBodyConfigOneNodesItemStatsItemLabelMax = 120

export const metricsPipelinesCreateBodyConfigOneNodesItemStatsItemFormatDefault = `count`
export const metricsPipelinesCreateBodyConfigOneNodesItemStatsItemFormatMax = 16

export const metricsPipelinesCreateBodyConfigOneNodesItemStatsItemMetricNameMax = 255

export const metricsPipelinesCreateBodyConfigOneNodesItemStatsItemAggregationDefault = `sum`
export const metricsPipelinesCreateBodyConfigOneNodesItemStatsItemAggregationMax = 32

export const metricsPipelinesCreateBodyConfigOneNodesItemStatsItemQuantileMin = 0
export const metricsPipelinesCreateBodyConfigOneNodesItemStatsItemQuantileMax = 1

export const metricsPipelinesCreateBodyConfigOneNodesItemStatsItemMetricTypeMax = 32

export const metricsPipelinesCreateBodyConfigOneNodesItemStatsItemFiltersItemKeyMax = 255

export const metricsPipelinesCreateBodyConfigOneNodesItemStatsItemFiltersItemOpDefault = `eq`
export const metricsPipelinesCreateBodyConfigOneNodesItemStatsItemFiltersItemOpMax = 16

export const metricsPipelinesCreateBodyConfigOneNodesItemStatsItemFiltersItemValueMax = 1024

export const metricsPipelinesCreateBodyConfigOneNodesItemStatsItemFiltersItemScopeDefault = `auto`
export const metricsPipelinesCreateBodyConfigOneNodesItemStatsItemFiltersItemScopeMax = 16

export const metricsPipelinesCreateBodyConfigOneNodesItemStatsItemBreakdownOneGroupByKeyMax = 255

export const metricsPipelinesCreateBodyConfigOneNodesItemStatsItemBreakdownOneTopNDefault = 10
export const metricsPipelinesCreateBodyConfigOneNodesItemStatsItemBreakdownOneTopNMax = 20

export const metricsPipelinesCreateBodyConfigOneNodesItemStatsItemBreakdownOneScopeDefault = `auto`
export const metricsPipelinesCreateBodyConfigOneNodesItemStatsItemBreakdownOneScopeMax = 16

export const metricsPipelinesCreateBodyConfigOneNodesItemHeadlineStatIdsItemMax = 64

export const metricsPipelinesCreateBodyConfigOneNodesItemLinksItemLabelMax = 120

export const metricsPipelinesCreateBodyConfigOneNodesItemLinksItemUrlMax = 2048

export const metricsPipelinesCreateBodyConfigOneNodesItemNoteDefault = ``
export const metricsPipelinesCreateBodyConfigOneEdgesItemSourceMax = 64

export const metricsPipelinesCreateBodyConfigOneEdgesItemTargetMax = 64

export const metricsPipelinesCreateBodyConfigOneEdgesItemMetricNameMax = 255

export const metricsPipelinesCreateBodyConfigOneEdgesItemAggregationDefault = `sum`
export const metricsPipelinesCreateBodyConfigOneEdgesItemAggregationMax = 32

export const metricsPipelinesCreateBodyConfigOneEdgesItemQuantileMin = 0
export const metricsPipelinesCreateBodyConfigOneEdgesItemQuantileMax = 1

export const metricsPipelinesCreateBodyConfigOneEdgesItemMetricTypeMax = 32

export const metricsPipelinesCreateBodyConfigOneEdgesItemFiltersItemKeyMax = 255

export const metricsPipelinesCreateBodyConfigOneEdgesItemFiltersItemOpDefault = `eq`
export const metricsPipelinesCreateBodyConfigOneEdgesItemFiltersItemOpMax = 16

export const metricsPipelinesCreateBodyConfigOneEdgesItemFiltersItemValueMax = 1024

export const metricsPipelinesCreateBodyConfigOneEdgesItemFiltersItemScopeDefault = `auto`
export const metricsPipelinesCreateBodyConfigOneEdgesItemFiltersItemScopeMax = 16

export const metricsPipelinesCreateBodyConfigOneEdgesItemBaselineOffsetDefault = `-7d`
export const metricsPipelinesCreateBodyConfigOneEdgesItemBaselineOffsetMax = 16

export const metricsPipelinesCreateBodyConfigOneEdgesItemHotMultiplierDefault = 2
export const metricsPipelinesCreateBodyConfigOneVariablesItemKeyMax = 64

export const metricsPipelinesCreateBodyConfigOneVariablesItemLabelMax = 120

export const metricsPipelinesCreateBodyConfigOneVariablesItemFilterKeyMax = 255

export const metricsPipelinesCreateBodyConfigOneVariablesItemOptionsItemMax = 255

export const metricsPipelinesCreateBodyConfigOneVariablesItemDefaultMax = 255

export const metricsPipelinesCreateBodyEnabledDefault = true

export const MetricsPipelinesCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(metricsPipelinesCreateBodyNameMax).describe('Display name of the pipeline.'),
        description: zod
            .string()
            .default(metricsPipelinesCreateBodyDescriptionDefault)
            .describe('What this pipeline observes and who owns it.'),
        config: zod
            .object({
                nodes: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(metricsPipelinesCreateBodyConfigOneNodesItemIdMax)
                                .describe('Node id, unique within the pipeline; edges reference it.'),
                            name: zod
                                .string()
                                .max(metricsPipelinesCreateBodyConfigOneNodesItemNameMax)
                                .describe('Display name of the component.'),
                            kind: zod
                                .string()
                                .max(metricsPipelinesCreateBodyConfigOneNodesItemKindMax)
                                .default(metricsPipelinesCreateBodyConfigOneNodesItemKindDefault)
                                .describe('Free-form component kind subtitle.'),
                            stats: zod
                                .array(
                                    zod.object({
                                        id: zod
                                            .string()
                                            .max(metricsPipelinesCreateBodyConfigOneNodesItemStatsItemIdMax)
                                            .describe('Stat id, unique within its node.'),
                                        label: zod
                                            .string()
                                            .max(metricsPipelinesCreateBodyConfigOneNodesItemStatsItemLabelMax)
                                            .describe('Display label for the stat.'),
                                        format: zod
                                            .string()
                                            .max(metricsPipelinesCreateBodyConfigOneNodesItemStatsItemFormatMax)
                                            .default(metricsPipelinesCreateBodyConfigOneNodesItemStatsItemFormatDefault)
                                            .describe(
                                                "Display format hint: 'rate', 'bytes', 'pct', 'count', or 'duration'."
                                            ),
                                        metric_name: zod
                                            .string()
                                            .max(metricsPipelinesCreateBodyConfigOneNodesItemStatsItemMetricNameMax)
                                            .describe('Exact ingested metric name this stat queries.'),
                                        aggregation: zod
                                            .string()
                                            .max(metricsPipelinesCreateBodyConfigOneNodesItemStatsItemAggregationMax)
                                            .default(
                                                metricsPipelinesCreateBodyConfigOneNodesItemStatsItemAggregationDefault
                                            )
                                            .describe(
                                                "Aggregation per time bucket: 'sum', 'avg', 'count', 'rate', 'increase', 'quantile', or 'histogram_quantile'."
                                            ),
                                        quantile: zod
                                            .number()
                                            .min(metricsPipelinesCreateBodyConfigOneNodesItemStatsItemQuantileMin)
                                            .max(metricsPipelinesCreateBodyConfigOneNodesItemStatsItemQuantileMax)
                                            .nullish()
                                            .describe('Quantile in (0, 1) for the quantile aggregations.'),
                                        metric_type: zod
                                            .string()
                                            .max(metricsPipelinesCreateBodyConfigOneNodesItemStatsItemMetricTypeMax)
                                            .nullish()
                                            .describe(
                                                "Optional OTel metric type constraint (e.g. 'gauge', 'sum', 'histogram')."
                                            ),
                                        filters: zod
                                            .array(
                                                zod.object({
                                                    key: zod
                                                        .string()
                                                        .max(
                                                            metricsPipelinesCreateBodyConfigOneNodesItemStatsItemFiltersItemKeyMax
                                                        )
                                                        .describe("Attribute name to filter on (e.g. 'k8s.pod.name')."),
                                                    op: zod
                                                        .string()
                                                        .max(
                                                            metricsPipelinesCreateBodyConfigOneNodesItemStatsItemFiltersItemOpMax
                                                        )
                                                        .default(
                                                            metricsPipelinesCreateBodyConfigOneNodesItemStatsItemFiltersItemOpDefault
                                                        )
                                                        .describe(
                                                            "Comparison operator: one of 'eq', 'neq', 'regex', 'not_regex'."
                                                        ),
                                                    value: zod
                                                        .string()
                                                        .max(
                                                            metricsPipelinesCreateBodyConfigOneNodesItemStatsItemFiltersItemValueMax
                                                        )
                                                        .describe(
                                                            'Value to compare against; the pattern for regex operators.'
                                                        ),
                                                    scope: zod
                                                        .string()
                                                        .max(
                                                            metricsPipelinesCreateBodyConfigOneNodesItemStatsItemFiltersItemScopeMax
                                                        )
                                                        .default(
                                                            metricsPipelinesCreateBodyConfigOneNodesItemStatsItemFiltersItemScopeDefault
                                                        )
                                                        .describe(
                                                            "Where the attribute lives: 'resource', 'attribute', or 'auto'."
                                                        ),
                                                })
                                            )
                                            .optional()
                                            .describe("Label predicates ANDed onto the stat's query."),
                                        thresholds: zod
                                            .union([
                                                zod.object({
                                                    warn: zod
                                                        .union([
                                                            zod.object({
                                                                lower: zod
                                                                    .number()
                                                                    .nullish()
                                                                    .describe(
                                                                        'Values below this breach the severity. Omit for no lower bound.'
                                                                    ),
                                                                upper: zod
                                                                    .number()
                                                                    .nullish()
                                                                    .describe(
                                                                        'Values above this breach the severity. Omit for no upper bound.'
                                                                    ),
                                                            }),
                                                            zod.null(),
                                                        ])
                                                        .optional()
                                                        .describe('Bounds whose breach marks the stat degraded.'),
                                                    crit: zod
                                                        .union([
                                                            zod.object({
                                                                lower: zod
                                                                    .number()
                                                                    .nullish()
                                                                    .describe(
                                                                        'Values below this breach the severity. Omit for no lower bound.'
                                                                    ),
                                                                upper: zod
                                                                    .number()
                                                                    .nullish()
                                                                    .describe(
                                                                        'Values above this breach the severity. Omit for no upper bound.'
                                                                    ),
                                                            }),
                                                            zod.null(),
                                                        ])
                                                        .optional()
                                                        .describe('Bounds whose breach marks the stat critical.'),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe("Warn\/crit bounds evaluated against the stat's latest value."),
                                        breakdown: zod
                                            .union([
                                                zod.object({
                                                    group_by_key: zod
                                                        .string()
                                                        .max(
                                                            metricsPipelinesCreateBodyConfigOneNodesItemStatsItemBreakdownOneGroupByKeyMax
                                                        )
                                                        .describe(
                                                            "Label to split the stat's breakdown table by (e.g. 'partition_id')."
                                                        ),
                                                    top_n: zod
                                                        .number()
                                                        .min(1)
                                                        .max(
                                                            metricsPipelinesCreateBodyConfigOneNodesItemStatsItemBreakdownOneTopNMax
                                                        )
                                                        .default(
                                                            metricsPipelinesCreateBodyConfigOneNodesItemStatsItemBreakdownOneTopNDefault
                                                        )
                                                        .describe(
                                                            "Rows shown before the remainder rolls into one 'others' row."
                                                        ),
                                                    scope: zod
                                                        .string()
                                                        .max(
                                                            metricsPipelinesCreateBodyConfigOneNodesItemStatsItemBreakdownOneScopeMax
                                                        )
                                                        .default(
                                                            metricsPipelinesCreateBodyConfigOneNodesItemStatsItemBreakdownOneScopeDefault
                                                        )
                                                        .describe(
                                                            "Attribute scope: 'resource', 'attribute', or 'auto'."
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Optional per-label breakdown table under the stat.'),
                                    })
                                )
                                .describe('Health stats on this node (at most 12).'),
                            headline_stat_ids: zod
                                .array(
                                    zod.string().max(metricsPipelinesCreateBodyConfigOneNodesItemHeadlineStatIdsItemMax)
                                )
                                .optional()
                                .describe('Stat ids shown on the collapsed node card, in order.'),
                            links: zod
                                .array(
                                    zod.object({
                                        label: zod
                                            .string()
                                            .max(metricsPipelinesCreateBodyConfigOneNodesItemLinksItemLabelMax)
                                            .describe('Link text shown on the drill panel.'),
                                        url: zod
                                            .string()
                                            .max(metricsPipelinesCreateBodyConfigOneNodesItemLinksItemUrlMax)
                                            .describe('Destination URL.'),
                                    })
                                )
                                .optional()
                                .describe('External deep links shown on the drill panel.'),
                            note: zod
                                .string()
                                .default(metricsPipelinesCreateBodyConfigOneNodesItemNoteDefault)
                                .describe('Free-form operator note shown on the drill panel.'),
                        })
                    )
                    .describe('Topology nodes (at most 20).'),
                edges: zod
                    .array(
                        zod.object({
                            source: zod
                                .string()
                                .max(metricsPipelinesCreateBodyConfigOneEdgesItemSourceMax)
                                .describe('Upstream node id.'),
                            target: zod
                                .string()
                                .max(metricsPipelinesCreateBodyConfigOneEdgesItemTargetMax)
                                .describe('Downstream node id.'),
                            metric_name: zod
                                .string()
                                .max(metricsPipelinesCreateBodyConfigOneEdgesItemMetricNameMax)
                                .describe('Metric measuring throughput along this edge.'),
                            aggregation: zod
                                .string()
                                .max(metricsPipelinesCreateBodyConfigOneEdgesItemAggregationMax)
                                .default(metricsPipelinesCreateBodyConfigOneEdgesItemAggregationDefault)
                                .describe('Aggregation per time bucket; same vocabulary as stats.'),
                            quantile: zod
                                .number()
                                .min(metricsPipelinesCreateBodyConfigOneEdgesItemQuantileMin)
                                .max(metricsPipelinesCreateBodyConfigOneEdgesItemQuantileMax)
                                .nullish()
                                .describe('Quantile in (0, 1) for the quantile aggregations.'),
                            metric_type: zod
                                .string()
                                .max(metricsPipelinesCreateBodyConfigOneEdgesItemMetricTypeMax)
                                .nullish()
                                .describe('Optional OTel metric type constraint.'),
                            filters: zod
                                .array(
                                    zod.object({
                                        key: zod
                                            .string()
                                            .max(metricsPipelinesCreateBodyConfigOneEdgesItemFiltersItemKeyMax)
                                            .describe("Attribute name to filter on (e.g. 'k8s.pod.name')."),
                                        op: zod
                                            .string()
                                            .max(metricsPipelinesCreateBodyConfigOneEdgesItemFiltersItemOpMax)
                                            .default(metricsPipelinesCreateBodyConfigOneEdgesItemFiltersItemOpDefault)
                                            .describe("Comparison operator: one of 'eq', 'neq', 'regex', 'not_regex'."),
                                        value: zod
                                            .string()
                                            .max(metricsPipelinesCreateBodyConfigOneEdgesItemFiltersItemValueMax)
                                            .describe('Value to compare against; the pattern for regex operators.'),
                                        scope: zod
                                            .string()
                                            .max(metricsPipelinesCreateBodyConfigOneEdgesItemFiltersItemScopeMax)
                                            .default(
                                                metricsPipelinesCreateBodyConfigOneEdgesItemFiltersItemScopeDefault
                                            )
                                            .describe("Where the attribute lives: 'resource', 'attribute', or 'auto'."),
                                    })
                                )
                                .optional()
                                .describe("Label predicates ANDed onto the edge's query."),
                            baseline_offset: zod
                                .string()
                                .max(metricsPipelinesCreateBodyConfigOneEdgesItemBaselineOffsetMax)
                                .default(metricsPipelinesCreateBodyConfigOneEdgesItemBaselineOffsetDefault)
                                .describe("How far back the comparison window sits, e.g. '-7d', '-24h', '-1w'."),
                            hot_multiplier: zod
                                .number()
                                .default(metricsPipelinesCreateBodyConfigOneEdgesItemHotMultiplierDefault)
                                .describe('Current\/baseline ratio at which the edge renders hot. Must exceed 1.'),
                        })
                    )
                    .optional()
                    .describe('Directed flows between nodes; the graph must stay acyclic.'),
                variables: zod
                    .array(
                        zod.object({
                            key: zod
                                .string()
                                .max(metricsPipelinesCreateBodyConfigOneVariablesItemKeyMax)
                                .describe('Variable key referenced when evaluating.'),
                            label: zod
                                .string()
                                .max(metricsPipelinesCreateBodyConfigOneVariablesItemLabelMax)
                                .describe('Display label of the selector.'),
                            filter_key: zod
                                .string()
                                .max(metricsPipelinesCreateBodyConfigOneVariablesItemFilterKeyMax)
                                .describe("Metric label the chosen value filters on (e.g. 'k8s.cluster.name')."),
                            options: zod
                                .array(zod.string().max(metricsPipelinesCreateBodyConfigOneVariablesItemOptionsItemMax))
                                .optional()
                                .describe('Allowed values; empty accepts any value.'),
                            default: zod
                                .string()
                                .max(metricsPipelinesCreateBodyConfigOneVariablesItemDefaultMax)
                                .nullish()
                                .describe('Value applied when none is passed to evaluate.'),
                        })
                    )
                    .optional()
                    .describe('Pipeline-level selectors injected into every query.'),
            })
            .describe('The topology: nodes with health stats, edges with baselines.'),
        enabled: zod
            .boolean()
            .default(metricsPipelinesCreateBodyEnabledDefault)
            .describe('Disabled pipelines stay listed but are not evaluated.'),
    })
    .describe(
        'Write shape for create\/update. `config` is fully revalidated by\n`parse_pipeline_config` on every write.'
    )

/**
 * Patch a pipeline; omitted fields stay unchanged. The config is fully revalidated.
 */
export const metricsPipelinesPartialUpdateBodyNameMax = 400

export const metricsPipelinesPartialUpdateBodyDescriptionDefault = ``
export const metricsPipelinesPartialUpdateBodyConfigOneNodesItemIdMax = 64

export const metricsPipelinesPartialUpdateBodyConfigOneNodesItemNameMax = 120

export const metricsPipelinesPartialUpdateBodyConfigOneNodesItemKindDefault = ``
export const metricsPipelinesPartialUpdateBodyConfigOneNodesItemKindMax = 120

export const metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemIdMax = 64

export const metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemLabelMax = 120

export const metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemFormatDefault = `count`
export const metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemFormatMax = 16

export const metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemMetricNameMax = 255

export const metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemAggregationDefault = `sum`
export const metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemAggregationMax = 32

export const metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemQuantileMin = 0
export const metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemQuantileMax = 1

export const metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemMetricTypeMax = 32

export const metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemFiltersItemKeyMax = 255

export const metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemFiltersItemOpDefault = `eq`
export const metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemFiltersItemOpMax = 16

export const metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemFiltersItemValueMax = 1024

export const metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemFiltersItemScopeDefault = `auto`
export const metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemFiltersItemScopeMax = 16

export const metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemBreakdownOneGroupByKeyMax = 255

export const metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemBreakdownOneTopNDefault = 10
export const metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemBreakdownOneTopNMax = 20

export const metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemBreakdownOneScopeDefault = `auto`
export const metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemBreakdownOneScopeMax = 16

export const metricsPipelinesPartialUpdateBodyConfigOneNodesItemHeadlineStatIdsItemMax = 64

export const metricsPipelinesPartialUpdateBodyConfigOneNodesItemLinksItemLabelMax = 120

export const metricsPipelinesPartialUpdateBodyConfigOneNodesItemLinksItemUrlMax = 2048

export const metricsPipelinesPartialUpdateBodyConfigOneNodesItemNoteDefault = ``
export const metricsPipelinesPartialUpdateBodyConfigOneEdgesItemSourceMax = 64

export const metricsPipelinesPartialUpdateBodyConfigOneEdgesItemTargetMax = 64

export const metricsPipelinesPartialUpdateBodyConfigOneEdgesItemMetricNameMax = 255

export const metricsPipelinesPartialUpdateBodyConfigOneEdgesItemAggregationDefault = `sum`
export const metricsPipelinesPartialUpdateBodyConfigOneEdgesItemAggregationMax = 32

export const metricsPipelinesPartialUpdateBodyConfigOneEdgesItemQuantileMin = 0
export const metricsPipelinesPartialUpdateBodyConfigOneEdgesItemQuantileMax = 1

export const metricsPipelinesPartialUpdateBodyConfigOneEdgesItemMetricTypeMax = 32

export const metricsPipelinesPartialUpdateBodyConfigOneEdgesItemFiltersItemKeyMax = 255

export const metricsPipelinesPartialUpdateBodyConfigOneEdgesItemFiltersItemOpDefault = `eq`
export const metricsPipelinesPartialUpdateBodyConfigOneEdgesItemFiltersItemOpMax = 16

export const metricsPipelinesPartialUpdateBodyConfigOneEdgesItemFiltersItemValueMax = 1024

export const metricsPipelinesPartialUpdateBodyConfigOneEdgesItemFiltersItemScopeDefault = `auto`
export const metricsPipelinesPartialUpdateBodyConfigOneEdgesItemFiltersItemScopeMax = 16

export const metricsPipelinesPartialUpdateBodyConfigOneEdgesItemBaselineOffsetDefault = `-7d`
export const metricsPipelinesPartialUpdateBodyConfigOneEdgesItemBaselineOffsetMax = 16

export const metricsPipelinesPartialUpdateBodyConfigOneEdgesItemHotMultiplierDefault = 2
export const metricsPipelinesPartialUpdateBodyConfigOneVariablesItemKeyMax = 64

export const metricsPipelinesPartialUpdateBodyConfigOneVariablesItemLabelMax = 120

export const metricsPipelinesPartialUpdateBodyConfigOneVariablesItemFilterKeyMax = 255

export const metricsPipelinesPartialUpdateBodyConfigOneVariablesItemOptionsItemMax = 255

export const metricsPipelinesPartialUpdateBodyConfigOneVariablesItemDefaultMax = 255

export const metricsPipelinesPartialUpdateBodyEnabledDefault = true

export const MetricsPipelinesPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(metricsPipelinesPartialUpdateBodyNameMax)
            .optional()
            .describe('Display name of the pipeline.'),
        description: zod
            .string()
            .default(metricsPipelinesPartialUpdateBodyDescriptionDefault)
            .describe('What this pipeline observes and who owns it.'),
        config: zod
            .object({
                nodes: zod
                    .array(
                        zod.object({
                            id: zod
                                .string()
                                .max(metricsPipelinesPartialUpdateBodyConfigOneNodesItemIdMax)
                                .describe('Node id, unique within the pipeline; edges reference it.'),
                            name: zod
                                .string()
                                .max(metricsPipelinesPartialUpdateBodyConfigOneNodesItemNameMax)
                                .describe('Display name of the component.'),
                            kind: zod
                                .string()
                                .max(metricsPipelinesPartialUpdateBodyConfigOneNodesItemKindMax)
                                .default(metricsPipelinesPartialUpdateBodyConfigOneNodesItemKindDefault)
                                .describe('Free-form component kind subtitle.'),
                            stats: zod
                                .array(
                                    zod.object({
                                        id: zod
                                            .string()
                                            .max(metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemIdMax)
                                            .describe('Stat id, unique within its node.'),
                                        label: zod
                                            .string()
                                            .max(metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemLabelMax)
                                            .describe('Display label for the stat.'),
                                        format: zod
                                            .string()
                                            .max(metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemFormatMax)
                                            .default(
                                                metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemFormatDefault
                                            )
                                            .describe(
                                                "Display format hint: 'rate', 'bytes', 'pct', 'count', or 'duration'."
                                            ),
                                        metric_name: zod
                                            .string()
                                            .max(
                                                metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemMetricNameMax
                                            )
                                            .describe('Exact ingested metric name this stat queries.'),
                                        aggregation: zod
                                            .string()
                                            .max(
                                                metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemAggregationMax
                                            )
                                            .default(
                                                metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemAggregationDefault
                                            )
                                            .describe(
                                                "Aggregation per time bucket: 'sum', 'avg', 'count', 'rate', 'increase', 'quantile', or 'histogram_quantile'."
                                            ),
                                        quantile: zod
                                            .number()
                                            .min(
                                                metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemQuantileMin
                                            )
                                            .max(
                                                metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemQuantileMax
                                            )
                                            .nullish()
                                            .describe('Quantile in (0, 1) for the quantile aggregations.'),
                                        metric_type: zod
                                            .string()
                                            .max(
                                                metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemMetricTypeMax
                                            )
                                            .nullish()
                                            .describe(
                                                "Optional OTel metric type constraint (e.g. 'gauge', 'sum', 'histogram')."
                                            ),
                                        filters: zod
                                            .array(
                                                zod.object({
                                                    key: zod
                                                        .string()
                                                        .max(
                                                            metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemFiltersItemKeyMax
                                                        )
                                                        .describe("Attribute name to filter on (e.g. 'k8s.pod.name')."),
                                                    op: zod
                                                        .string()
                                                        .max(
                                                            metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemFiltersItemOpMax
                                                        )
                                                        .default(
                                                            metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemFiltersItemOpDefault
                                                        )
                                                        .describe(
                                                            "Comparison operator: one of 'eq', 'neq', 'regex', 'not_regex'."
                                                        ),
                                                    value: zod
                                                        .string()
                                                        .max(
                                                            metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemFiltersItemValueMax
                                                        )
                                                        .describe(
                                                            'Value to compare against; the pattern for regex operators.'
                                                        ),
                                                    scope: zod
                                                        .string()
                                                        .max(
                                                            metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemFiltersItemScopeMax
                                                        )
                                                        .default(
                                                            metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemFiltersItemScopeDefault
                                                        )
                                                        .describe(
                                                            "Where the attribute lives: 'resource', 'attribute', or 'auto'."
                                                        ),
                                                })
                                            )
                                            .optional()
                                            .describe("Label predicates ANDed onto the stat's query."),
                                        thresholds: zod
                                            .union([
                                                zod.object({
                                                    warn: zod
                                                        .union([
                                                            zod.object({
                                                                lower: zod
                                                                    .number()
                                                                    .nullish()
                                                                    .describe(
                                                                        'Values below this breach the severity. Omit for no lower bound.'
                                                                    ),
                                                                upper: zod
                                                                    .number()
                                                                    .nullish()
                                                                    .describe(
                                                                        'Values above this breach the severity. Omit for no upper bound.'
                                                                    ),
                                                            }),
                                                            zod.null(),
                                                        ])
                                                        .optional()
                                                        .describe('Bounds whose breach marks the stat degraded.'),
                                                    crit: zod
                                                        .union([
                                                            zod.object({
                                                                lower: zod
                                                                    .number()
                                                                    .nullish()
                                                                    .describe(
                                                                        'Values below this breach the severity. Omit for no lower bound.'
                                                                    ),
                                                                upper: zod
                                                                    .number()
                                                                    .nullish()
                                                                    .describe(
                                                                        'Values above this breach the severity. Omit for no upper bound.'
                                                                    ),
                                                            }),
                                                            zod.null(),
                                                        ])
                                                        .optional()
                                                        .describe('Bounds whose breach marks the stat critical.'),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe("Warn\/crit bounds evaluated against the stat's latest value."),
                                        breakdown: zod
                                            .union([
                                                zod.object({
                                                    group_by_key: zod
                                                        .string()
                                                        .max(
                                                            metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemBreakdownOneGroupByKeyMax
                                                        )
                                                        .describe(
                                                            "Label to split the stat's breakdown table by (e.g. 'partition_id')."
                                                        ),
                                                    top_n: zod
                                                        .number()
                                                        .min(1)
                                                        .max(
                                                            metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemBreakdownOneTopNMax
                                                        )
                                                        .default(
                                                            metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemBreakdownOneTopNDefault
                                                        )
                                                        .describe(
                                                            "Rows shown before the remainder rolls into one 'others' row."
                                                        ),
                                                    scope: zod
                                                        .string()
                                                        .max(
                                                            metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemBreakdownOneScopeMax
                                                        )
                                                        .default(
                                                            metricsPipelinesPartialUpdateBodyConfigOneNodesItemStatsItemBreakdownOneScopeDefault
                                                        )
                                                        .describe(
                                                            "Attribute scope: 'resource', 'attribute', or 'auto'."
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Optional per-label breakdown table under the stat.'),
                                    })
                                )
                                .describe('Health stats on this node (at most 12).'),
                            headline_stat_ids: zod
                                .array(
                                    zod
                                        .string()
                                        .max(metricsPipelinesPartialUpdateBodyConfigOneNodesItemHeadlineStatIdsItemMax)
                                )
                                .optional()
                                .describe('Stat ids shown on the collapsed node card, in order.'),
                            links: zod
                                .array(
                                    zod.object({
                                        label: zod
                                            .string()
                                            .max(metricsPipelinesPartialUpdateBodyConfigOneNodesItemLinksItemLabelMax)
                                            .describe('Link text shown on the drill panel.'),
                                        url: zod
                                            .string()
                                            .max(metricsPipelinesPartialUpdateBodyConfigOneNodesItemLinksItemUrlMax)
                                            .describe('Destination URL.'),
                                    })
                                )
                                .optional()
                                .describe('External deep links shown on the drill panel.'),
                            note: zod
                                .string()
                                .default(metricsPipelinesPartialUpdateBodyConfigOneNodesItemNoteDefault)
                                .describe('Free-form operator note shown on the drill panel.'),
                        })
                    )
                    .describe('Topology nodes (at most 20).'),
                edges: zod
                    .array(
                        zod.object({
                            source: zod
                                .string()
                                .max(metricsPipelinesPartialUpdateBodyConfigOneEdgesItemSourceMax)
                                .describe('Upstream node id.'),
                            target: zod
                                .string()
                                .max(metricsPipelinesPartialUpdateBodyConfigOneEdgesItemTargetMax)
                                .describe('Downstream node id.'),
                            metric_name: zod
                                .string()
                                .max(metricsPipelinesPartialUpdateBodyConfigOneEdgesItemMetricNameMax)
                                .describe('Metric measuring throughput along this edge.'),
                            aggregation: zod
                                .string()
                                .max(metricsPipelinesPartialUpdateBodyConfigOneEdgesItemAggregationMax)
                                .default(metricsPipelinesPartialUpdateBodyConfigOneEdgesItemAggregationDefault)
                                .describe('Aggregation per time bucket; same vocabulary as stats.'),
                            quantile: zod
                                .number()
                                .min(metricsPipelinesPartialUpdateBodyConfigOneEdgesItemQuantileMin)
                                .max(metricsPipelinesPartialUpdateBodyConfigOneEdgesItemQuantileMax)
                                .nullish()
                                .describe('Quantile in (0, 1) for the quantile aggregations.'),
                            metric_type: zod
                                .string()
                                .max(metricsPipelinesPartialUpdateBodyConfigOneEdgesItemMetricTypeMax)
                                .nullish()
                                .describe('Optional OTel metric type constraint.'),
                            filters: zod
                                .array(
                                    zod.object({
                                        key: zod
                                            .string()
                                            .max(metricsPipelinesPartialUpdateBodyConfigOneEdgesItemFiltersItemKeyMax)
                                            .describe("Attribute name to filter on (e.g. 'k8s.pod.name')."),
                                        op: zod
                                            .string()
                                            .max(metricsPipelinesPartialUpdateBodyConfigOneEdgesItemFiltersItemOpMax)
                                            .default(
                                                metricsPipelinesPartialUpdateBodyConfigOneEdgesItemFiltersItemOpDefault
                                            )
                                            .describe("Comparison operator: one of 'eq', 'neq', 'regex', 'not_regex'."),
                                        value: zod
                                            .string()
                                            .max(metricsPipelinesPartialUpdateBodyConfigOneEdgesItemFiltersItemValueMax)
                                            .describe('Value to compare against; the pattern for regex operators.'),
                                        scope: zod
                                            .string()
                                            .max(metricsPipelinesPartialUpdateBodyConfigOneEdgesItemFiltersItemScopeMax)
                                            .default(
                                                metricsPipelinesPartialUpdateBodyConfigOneEdgesItemFiltersItemScopeDefault
                                            )
                                            .describe("Where the attribute lives: 'resource', 'attribute', or 'auto'."),
                                    })
                                )
                                .optional()
                                .describe("Label predicates ANDed onto the edge's query."),
                            baseline_offset: zod
                                .string()
                                .max(metricsPipelinesPartialUpdateBodyConfigOneEdgesItemBaselineOffsetMax)
                                .default(metricsPipelinesPartialUpdateBodyConfigOneEdgesItemBaselineOffsetDefault)
                                .describe("How far back the comparison window sits, e.g. '-7d', '-24h', '-1w'."),
                            hot_multiplier: zod
                                .number()
                                .default(metricsPipelinesPartialUpdateBodyConfigOneEdgesItemHotMultiplierDefault)
                                .describe('Current\/baseline ratio at which the edge renders hot. Must exceed 1.'),
                        })
                    )
                    .optional()
                    .describe('Directed flows between nodes; the graph must stay acyclic.'),
                variables: zod
                    .array(
                        zod.object({
                            key: zod
                                .string()
                                .max(metricsPipelinesPartialUpdateBodyConfigOneVariablesItemKeyMax)
                                .describe('Variable key referenced when evaluating.'),
                            label: zod
                                .string()
                                .max(metricsPipelinesPartialUpdateBodyConfigOneVariablesItemLabelMax)
                                .describe('Display label of the selector.'),
                            filter_key: zod
                                .string()
                                .max(metricsPipelinesPartialUpdateBodyConfigOneVariablesItemFilterKeyMax)
                                .describe("Metric label the chosen value filters on (e.g. 'k8s.cluster.name')."),
                            options: zod
                                .array(
                                    zod
                                        .string()
                                        .max(metricsPipelinesPartialUpdateBodyConfigOneVariablesItemOptionsItemMax)
                                )
                                .optional()
                                .describe('Allowed values; empty accepts any value.'),
                            default: zod
                                .string()
                                .max(metricsPipelinesPartialUpdateBodyConfigOneVariablesItemDefaultMax)
                                .nullish()
                                .describe('Value applied when none is passed to evaluate.'),
                        })
                    )
                    .optional()
                    .describe('Pipeline-level selectors injected into every query.'),
            })
            .optional()
            .describe('The topology: nodes with health stats, edges with baselines.'),
        enabled: zod
            .boolean()
            .default(metricsPipelinesPartialUpdateBodyEnabledDefault)
            .describe('Disabled pipelines stay listed but are not evaluated.'),
    })
    .describe(
        'Write shape for create\/update. `config` is fully revalidated by\n`parse_pipeline_config` on every write.'
    )

/**
 * Evaluate every node stat and edge of the pipeline over one window and derive the alert strip.
 */
export const metricsPipelinesEvaluateCreateBodyVariablesMaxOne = 255

export const MetricsPipelinesEvaluateCreateBody = /* @__PURE__ */ zod.object({
    variables: zod
        .record(
            zod.string(),
            zod
                .string()
                .max(metricsPipelinesEvaluateCreateBodyVariablesMaxOne)
                .describe('Chosen value for the variable.')
        )
        .optional()
        .describe('Variable values keyed by variable key; unset variables fall back to their defaults.'),
    date_from: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('Window start (ISO 8601). Defaults to 30 minutes ago.'),
    date_to: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('Window end (ISO 8601), exclusive. Defaults to now.'),
})
