/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 2 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const MetricsQueryCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

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
                .describe('* `sum` - sum\n* `avg` - avg\n* `count` - count\n* `p95` - p95')
                .default(metricsQueryCreateBodyQueryOneAggregationDefault)
                .describe(
                    'Aggregation applied per time bucket.\n\n* `sum` - sum\n* `avg` - avg\n* `count` - count\n* `p95` - p95'
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

export const MetricsValuesRetrieveQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Max number of names to return. Defaults to 100, capped at 1000.'),
    value: zod.string().optional().describe('Substring filter (case-insensitive) applied to metric names.'),
})
