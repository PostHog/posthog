/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 3 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Characterize a metric anomaly: compare an anomaly window against a
 * baseline, find the onset, and rank which label values moved.
 */
export const MetricsCharacterizeCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
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
                            '* `sum` - sum\n* `avg` - avg\n* `count` - count\n* `p95` - p95\n* `rate` - rate\n* `increase` - increase\n* `histogram_quantile` - histogram_quantile'
                        ),
                    zod.null(),
                ])
                .optional()
                .describe(
                    "Aggregation to characterize. Omit to auto-pick from the metric's OTel type (counter -> rate, gauge -> avg, histogram -> histogram_quantile 0.95).\n\n* `sum` - sum\n* `avg` - avg\n* `count` - count\n* `p95` - p95\n* `rate` - rate\n* `increase` - increase\n* `histogram_quantile` - histogram_quantile"
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
                            .describe('* `eq` - eq\n* `neq` - neq\n* `regex` - regex\n* `not_regex` - not_regex')
                            .default(metricsCharacterizeCreateBodyQueryOneFiltersItemOpDefault)
                            .describe(
                                "Comparison operator. 'regex'/'not_regex' use RE2 syntax. Negative operators also match rows that lack the key entirely, mirroring Prometheus negative matchers.\n\n* `eq` - eq\n* `neq` - neq\n* `regex` - regex\n* `not_regex` - not_regex"
                            ),
                        value: zod
                            .string()
                            .max(metricsCharacterizeCreateBodyQueryOneFiltersItemValueMax)
                            .describe('Value to compare against. For regex operators this is the pattern.'),
                        scope: zod
                            .enum(['resource', 'attribute', 'auto'])
                            .describe('* `resource` - resource\n* `attribute` - attribute\n* `auto` - auto')
                            .default(metricsCharacterizeCreateBodyQueryOneFiltersItemScopeDefault)
                            .describe(
                                "Where the attribute lives: 'resource' = per-target resource attributes (k8s.pod.name, service.version), 'attribute' = per-datapoint attributes (http.method, path), 'auto' = resource first with per-datapoint fallback. Use 'auto' unless you know the exact scope.\n\n* `resource` - resource\n* `attribute` - attribute\n* `auto` - auto"
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

export const MetricsQueryCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
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
            aggregation: zod
                .enum(['sum', 'avg', 'count', 'p95', 'rate', 'increase', 'histogram_quantile'])
                .describe(
                    '* `sum` - sum\n* `avg` - avg\n* `count` - count\n* `p95` - p95\n* `rate` - rate\n* `increase` - increase\n* `histogram_quantile` - histogram_quantile'
                )
                .default(metricsQueryCreateBodyQueryOneAggregationDefault)
                .describe(
                    "Aggregation applied per time bucket. 'rate' (per-second) and 'increase' are counter-aware: per-series deltas with Prometheus counter-reset handling, temporality-aware (delta-temporality samples count as-is). 'histogram_quantile' interpolates from OTel histogram buckets and requires 'quantile'.\n\n* `sum` - sum\n* `avg` - avg\n* `count` - count\n* `p95` - p95\n* `rate` - rate\n* `increase` - increase\n* `histogram_quantile` - histogram_quantile"
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
                            .describe('* `eq` - eq\n* `neq` - neq\n* `regex` - regex\n* `not_regex` - not_regex')
                            .default(metricsQueryCreateBodyQueryOneFiltersItemOpDefault)
                            .describe(
                                "Comparison operator. 'regex'/'not_regex' use RE2 syntax. Negative operators also match rows that lack the key entirely, mirroring Prometheus negative matchers.\n\n* `eq` - eq\n* `neq` - neq\n* `regex` - regex\n* `not_regex` - not_regex"
                            ),
                        value: zod
                            .string()
                            .max(metricsQueryCreateBodyQueryOneFiltersItemValueMax)
                            .describe('Value to compare against. For regex operators this is the pattern.'),
                        scope: zod
                            .enum(['resource', 'attribute', 'auto'])
                            .describe('* `resource` - resource\n* `attribute` - attribute\n* `auto` - auto')
                            .default(metricsQueryCreateBodyQueryOneFiltersItemScopeDefault)
                            .describe(
                                "Where the attribute lives: 'resource' = per-target resource attributes (k8s.pod.name, service.version), 'attribute' = per-datapoint attributes (http.method, path), 'auto' = resource first with per-datapoint fallback. Use 'auto' unless you know the exact scope.\n\n* `resource` - resource\n* `attribute` - attribute\n* `auto` - auto"
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
                            .describe('* `resource` - resource\n* `attribute` - attribute\n* `auto` - auto')
                            .default(metricsQueryCreateBodyQueryOneGroupByItemScopeDefault)
                            .describe(
                                "Where the attribute lives; same semantics as filter scope. Use 'auto' unless you know the exact scope.\n\n* `resource` - resource\n* `attribute` - attribute\n* `auto` - auto"
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
                            '* `second` - second\n* `minute` - minute\n* `minute_5` - minute_5\n* `minute_15` - minute_15\n* `hour` - hour\n* `hour_6` - hour_6\n* `day` - day\n* `week` - week'
                        ),
                    zod.null(),
                ])
                .optional()
                .describe(
                    'Bucket size for the shared time grid. Omit to auto-pick (~60 buckets across the range).\n\n* `second` - second\n* `minute` - minute\n* `minute_5` - minute_5\n* `minute_15` - minute_15\n* `hour` - hour\n* `hour_6` - hour_6\n* `day` - day\n* `week` - week'
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
                        aggregation: zod
                            .enum(['sum', 'avg', 'count', 'p95', 'rate', 'increase', 'histogram_quantile'])
                            .describe(
                                '* `sum` - sum\n* `avg` - avg\n* `count` - count\n* `p95` - p95\n* `rate` - rate\n* `increase` - increase\n* `histogram_quantile` - histogram_quantile'
                            )
                            .default(metricsQueryCreateBodyQueryOneClausesItemAggregationDefault)
                            .describe(
                                'Aggregation applied per time bucket; same semantics as the top-level aggregation.\n\n* `sum` - sum\n* `avg` - avg\n* `count` - count\n* `p95` - p95\n* `rate` - rate\n* `increase` - increase\n* `histogram_quantile` - histogram_quantile'
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
                                            '* `eq` - eq\n* `neq` - neq\n* `regex` - regex\n* `not_regex` - not_regex'
                                        )
                                        .default(metricsQueryCreateBodyQueryOneClausesItemFiltersItemOpDefault)
                                        .describe(
                                            "Comparison operator. 'regex'/'not_regex' use RE2 syntax. Negative operators also match rows that lack the key entirely, mirroring Prometheus negative matchers.\n\n* `eq` - eq\n* `neq` - neq\n* `regex` - regex\n* `not_regex` - not_regex"
                                        ),
                                    value: zod
                                        .string()
                                        .max(metricsQueryCreateBodyQueryOneClausesItemFiltersItemValueMax)
                                        .describe('Value to compare against. For regex operators this is the pattern.'),
                                    scope: zod
                                        .enum(['resource', 'attribute', 'auto'])
                                        .describe('* `resource` - resource\n* `attribute` - attribute\n* `auto` - auto')
                                        .default(metricsQueryCreateBodyQueryOneClausesItemFiltersItemScopeDefault)
                                        .describe(
                                            "Where the attribute lives: 'resource' = per-target resource attributes (k8s.pod.name, service.version), 'attribute' = per-datapoint attributes (http.method, path), 'auto' = resource first with per-datapoint fallback. Use 'auto' unless you know the exact scope.\n\n* `resource` - resource\n* `attribute` - attribute\n* `auto` - auto"
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
                                        .describe('* `resource` - resource\n* `attribute` - attribute\n* `auto` - auto')
                                        .default(metricsQueryCreateBodyQueryOneClausesItemGroupByItemScopeDefault)
                                        .describe(
                                            "Where the attribute lives; same semantics as filter scope. Use 'auto' unless you know the exact scope.\n\n* `resource` - resource\n* `attribute` - attribute\n* `auto` - auto"
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
                    "Arithmetic over clause names evaluated server-side per grid point, e.g. '(a - b) / a'. Supports + - * / and parentheses; division by zero yields 0. When set, only the formula result series are returned."
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
 * Distinct metric names for the team. Backs the picker UI.
 */
export const MetricsValuesRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const metricsValuesRetrieveQueryLimitDefault = 100
export const metricsValuesRetrieveQueryLimitMax = 1000

export const metricsValuesRetrieveQueryValueDefault = ``
export const metricsValuesRetrieveQueryValueMax = 255

export const MetricsValuesRetrieveQueryParams = /* @__PURE__ */ zod.object({
    limit: zod
        .number()
        .min(1)
        .max(metricsValuesRetrieveQueryLimitMax)
        .default(metricsValuesRetrieveQueryLimitDefault)
        .describe('Max number of names to return. Defaults to 100; maximum 1000.'),
    value: zod
        .string()
        .max(metricsValuesRetrieveQueryValueMax)
        .default(metricsValuesRetrieveQueryValueDefault)
        .describe('Substring filter (case-insensitive) applied to metric names.'),
})
