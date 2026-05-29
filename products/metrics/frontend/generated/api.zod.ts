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
