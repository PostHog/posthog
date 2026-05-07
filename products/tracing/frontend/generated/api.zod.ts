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
 * Aggregates logs + trace_spans joinability and service-name overlap for agents.
 */
export const ObservabilitySignalSnapshotCreateBody = /* @__PURE__ */ zod.object({
    dateRange: zod
        .object({
            date_from: zod
                .string()
                .nullish()
                .describe('Start of the range. ISO 8601 or relative (-1h, -24h, -7d). Defaults to -24h when omitted.'),
            date_to: zod
                .string()
                .nullish()
                .describe('End of the range. Same format as date_from. Omit or null for \"now\".'),
        })
        .optional()
        .describe('Time window for both logs and span aggregates. Defaults to last 24 hours.'),
    serviceNames: zod
        .array(zod.string())
        .optional()
        .describe('When set, restrict log and span aggregates to these service_name values.'),
})

export const tracingSpansQueryCreateBodyQueryOneFilterGroupDefault = []
export const tracingSpansQueryCreateBodyQueryOneLimitDefault = 100
export const tracingSpansQueryCreateBodyQueryOneRootSpansDefault = true

export const TracingSpansQueryCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .object({
            dateRange: zod
                .object({
                    date_from: zod
                        .string()
                        .nullish()
                        .describe(
                            'Start of the date range. Accepts ISO 8601 timestamps or relative formats: -1h, -6h, -1d, -7d, etc.'
                        ),
                    date_to: zod
                        .string()
                        .nullish()
                        .describe('End of the date range. Same format as date_from. Omit or null for \"now\".'),
                })
                .optional()
                .describe('Date range for the query. Defaults to last hour.'),
            serviceNames: zod.array(zod.string()).optional().describe('Filter by service names.'),
            statusCodes: zod
                .array(zod.number())
                .optional()
                .describe(
                    'Filter by OpenTelemetry span status_code (0=Unset, 1=OK, 2=Error). For HTTP response codes (e.g. 500), use filterGroup on span_attribute key http.status_code.'
                ),
            orderBy: zod
                .enum(['latest', 'earliest'])
                .describe('* `latest` - latest\n* `earliest` - earliest')
                .optional()
                .describe(
                    'Order results by timestamp. Defaults to latest.\n\n* `latest` - latest\n* `earliest` - earliest'
                ),
            filterGroup: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .describe(
                                'Attribute key. For type \"span\", use built-in fields (trace_id, span_id, duration, name, kind, status_code). For \"span_attribute\"/\"span_resource_attribute\", use the attribute key (e.g. \"http.method\").'
                            ),
                        type: zod
                            .enum(['span', 'span_attribute', 'span_resource_attribute'])
                            .describe(
                                '* `span` - span\n* `span_attribute` - span_attribute\n* `span_resource_attribute` - span_resource_attribute'
                            )
                            .describe(
                                '\"span\" filters built-in span fields. \"span_attribute\" filters span-level attributes. \"span_resource_attribute\" filters resource-level attributes.\n\n* `span` - span\n* `span_attribute` - span_attribute\n* `span_resource_attribute` - span_resource_attribute'
                            ),
                        operator: zod
                            .enum([
                                'exact',
                                'is_not',
                                'icontains',
                                'not_icontains',
                                'regex',
                                'not_regex',
                                'gt',
                                'lt',
                                'is_set',
                                'is_not_set',
                            ])
                            .describe(
                                '* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                            )
                            .describe(
                                'Comparison operator.\n\n* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                            ),
                        value: zod
                            .unknown()
                            .nullish()
                            .describe(
                                'Value to compare against. String, number, or array of strings. Omit for is_set/is_not_set operators.'
                            ),
                    })
                )
                .default(tracingSpansQueryCreateBodyQueryOneFilterGroupDefault)
                .describe('Property filters for the query.'),
            traceId: zod.string().optional().describe('Filter to a specific trace ID (hex string).'),
            limit: zod
                .number()
                .default(tracingSpansQueryCreateBodyQueryOneLimitDefault)
                .describe('Max results (1-1000). Defaults to 100.'),
            after: zod.string().optional().describe('Pagination cursor from previous response.'),
            rootSpans: zod
                .boolean()
                .default(tracingSpansQueryCreateBodyQueryOneRootSpansDefault)
                .describe('Filter to root spans only. Defaults to true.'),
            prefetchSpans: zod.number().optional().describe('Number of child spans to prefetch per trace (1-100).'),
        })
        .describe('The tracing spans query to execute.'),
})

export const tracingSpansSparklineCreateBodyQueryOneFilterGroupDefault = []

export const TracingSpansSparklineCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .object({
            dateRange: zod
                .object({
                    date_from: zod
                        .string()
                        .nullish()
                        .describe(
                            'Start of the date range. Accepts ISO 8601 timestamps or relative formats: -1h, -6h, -1d, -7d, etc.'
                        ),
                    date_to: zod
                        .string()
                        .nullish()
                        .describe('End of the date range. Same format as date_from. Omit or null for \"now\".'),
                })
                .optional()
                .describe('Date range for the sparkline. Defaults to last hour.'),
            serviceNames: zod.array(zod.string()).optional().describe('Optional filter to one or more service names.'),
            statusCodes: zod
                .array(zod.number())
                .optional()
                .describe('Filter by OpenTelemetry span status_code (0=Unset, 1=OK, 2=Error).'),
            filterGroup: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .describe(
                                'Attribute key. For type \"span\", use built-in fields (trace_id, span_id, duration, name, kind, status_code). For \"span_attribute\"/\"span_resource_attribute\", use the attribute key (e.g. \"http.method\").'
                            ),
                        type: zod
                            .enum(['span', 'span_attribute', 'span_resource_attribute'])
                            .describe(
                                '* `span` - span\n* `span_attribute` - span_attribute\n* `span_resource_attribute` - span_resource_attribute'
                            )
                            .describe(
                                '\"span\" filters built-in span fields. \"span_attribute\" filters span-level attributes. \"span_resource_attribute\" filters resource-level attributes.\n\n* `span` - span\n* `span_attribute` - span_attribute\n* `span_resource_attribute` - span_resource_attribute'
                            ),
                        operator: zod
                            .enum([
                                'exact',
                                'is_not',
                                'icontains',
                                'not_icontains',
                                'regex',
                                'not_regex',
                                'gt',
                                'lt',
                                'is_set',
                                'is_not_set',
                            ])
                            .describe(
                                '* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                            )
                            .describe(
                                'Comparison operator.\n\n* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                            ),
                        value: zod
                            .unknown()
                            .nullish()
                            .describe(
                                'Value to compare against. String, number, or array of strings. Omit for is_set/is_not_set operators.'
                            ),
                    })
                )
                .default(tracingSpansSparklineCreateBodyQueryOneFilterGroupDefault)
                .describe('Property filters (same shape as span query).'),
        })
        .describe('Filters and date range for the sparkline aggregation.'),
})

export const tracingSpansTraceCreateBodyMaxSpansDefault = 2000
export const tracingSpansTraceCreateBodyMaxSpansMax = 5000

export const TracingSpansTraceCreateBody = /* @__PURE__ */ zod.object({
    dateRange: zod
        .object({
            date_from: zod
                .string()
                .nullish()
                .describe(
                    'Start of the date range. Accepts ISO 8601 timestamps or relative formats: -1h, -6h, -1d, -7d, etc.'
                ),
            date_to: zod
                .string()
                .nullish()
                .describe('End of the date range. Same format as date_from. Omit or null for \"now\".'),
        })
        .optional()
        .describe('Date range for the query. Defaults to last 24 hours.'),
    maxSpans: zod
        .number()
        .min(1)
        .max(tracingSpansTraceCreateBodyMaxSpansMax)
        .default(tracingSpansTraceCreateBodyMaxSpansDefault)
        .describe('Maximum spans to return for this trace (default 2000). Lower for agents; raise for deep traces.'),
})
