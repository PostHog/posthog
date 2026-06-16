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

export const metricsQueryCreateBodyQueryOneMetricNameMax = 255

export const metricsQueryCreateBodyQueryOneAggregationDefault = `sum`
export const metricsQueryCreateBodyQueryOneFiltersItemKeyMax = 255

export const metricsQueryCreateBodyQueryOneFiltersItemOpDefault = `eq`
export const metricsQueryCreateBodyQueryOneFiltersItemScopeDefault = `auto`
export const metricsQueryCreateBodyQueryOneGroupByItemKeyMax = 255

export const metricsQueryCreateBodyQueryOneGroupByItemScopeDefault = `auto`

export const MetricsQueryCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .object({
            metricName: zod
                .string()
                .max(metricsQueryCreateBodyQueryOneMetricNameMax)
                .describe("Exact metric name to query (e.g. 'http.server.duration')."),
            aggregation: zod
                .enum(['sum', 'avg', 'count', 'p95'])
                .describe('\* `sum` - sum\n\* `avg` - avg\n\* `count` - count\n\* `p95` - p95')
                .default(metricsQueryCreateBodyQueryOneAggregationDefault)
                .describe(
                    'Aggregation applied per time bucket.\n\n\* `sum` - sum\n\* `avg` - avg\n\* `count` - count\n\* `p95` - p95'
                ),
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
