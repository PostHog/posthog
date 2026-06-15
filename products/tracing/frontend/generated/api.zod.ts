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

export const tracingSpansAggregateCreateBodyQueryOneCompareFilterOneCompareDefault = false
export const tracingSpansAggregateCreateBodyQueryOneFilterGroupDefault = []

export const TracingSpansAggregateCreateBody = /* @__PURE__ */ zod.object({
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
                .describe('Date range for the primary window. Defaults to last hour.'),
            compareFilter: zod
                .object({
                    compare: zod
                        .boolean()
                        .default(tracingSpansAggregateCreateBodyQueryOneCompareFilterOneCompareDefault)
                        .describe(
                            'When true, also fetch results for a comparison window and return them under `compare`.'
                        ),
                    compare_to: zod
                        .string()
                        .nullish()
                        .describe(
                            "Relative date offset for the comparison window (e.g. '-1h', '-1d', '-7d'). Defaults to the immediately previous period of equal length."
                        ),
                })
                .optional()
                .describe(
                    'Optional comparison-window configuration. When omitted, only the primary window is returned.'
                ),
            serviceNames: zod.array(zod.string()).optional().describe('Filter by service names.'),
            filterGroup: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .describe(
                                'Attribute key. For type \"span\", use built-in fields (trace_id, span_id, duration, name, kind, status_code, is_root_span). For \"span_attribute\"\/\"span_resource_attribute\", use the attribute key (e.g. \"http.method\").'
                            ),
                        type: zod
                            .enum(['span', 'span_attribute', 'span_resource_attribute'])
                            .describe(
                                '\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                            )
                            .describe(
                                '\"span\" filters built-in span fields. \"span_attribute\" filters span-level attributes. \"span_resource_attribute\" filters resource-level attributes.\n\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
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
                                '\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                            )
                            .describe(
                                'Comparison operator.\n\n\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                            ),
                        value: zod
                            .unknown()
                            .optional()
                            .describe(
                                'Value to compare against. String, number, or array of strings. Omit for is_set\/is_not_set operators.'
                            ),
                    })
                )
                .default(tracingSpansAggregateCreateBodyQueryOneFilterGroupDefault)
                .describe('Property filters applied to spans in both windows.'),
        })
        .describe('The span aggregation query to execute.'),
})

export const tracingSpansCountCreateBodyQueryOneFilterGroupDefault = []

export const TracingSpansCountCreateBody = /* @__PURE__ */ zod.object({
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
                .describe('Date range for the count. Defaults to last hour.'),
            serviceNames: zod.array(zod.string()).optional().describe('Filter by service names.'),
            statusCodes: zod
                .array(zod.number())
                .optional()
                .describe(
                    'Filter by OTel span status codes (0 Unset, 1 OK, 2 Error) — not HTTP status codes. Use [2] to select error spans.'
                ),
            filterGroup: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .describe(
                                'Attribute key. For type \"span\", use built-in fields (trace_id, span_id, duration, name, kind, status_code, is_root_span). For \"span_attribute\"\/\"span_resource_attribute\", use the attribute key (e.g. \"http.method\").'
                            ),
                        type: zod
                            .enum(['span', 'span_attribute', 'span_resource_attribute'])
                            .describe(
                                '\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                            )
                            .describe(
                                '\"span\" filters built-in span fields. \"span_attribute\" filters span-level attributes. \"span_resource_attribute\" filters resource-level attributes.\n\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
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
                                '\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                            )
                            .describe(
                                'Comparison operator.\n\n\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                            ),
                        value: zod
                            .unknown()
                            .optional()
                            .describe(
                                'Value to compare against. String, number, or array of strings. Omit for is_set\/is_not_set operators.'
                            ),
                    })
                )
                .default(tracingSpansCountCreateBodyQueryOneFilterGroupDefault)
                .describe('Property filters for the count.'),
        })
        .describe('The span count query to execute.'),
})

export const tracingSpansDurationHistogramCreateBodyQueryOneFilterGroupDefault = []
export const tracingSpansDurationHistogramCreateBodyQueryOneLimitDefault = 100
export const tracingSpansDurationHistogramCreateBodyQueryOneOffsetMin = 0

export const tracingSpansDurationHistogramCreateBodyQueryOneRootSpansDefault = true
export const tracingSpansDurationHistogramCreateBodyQueryOneExcludeAttributesDefault = false

export const TracingSpansDurationHistogramCreateBody = /* @__PURE__ */ zod.object({
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
                    'Filter by OTel span status codes (0 Unset, 1 OK, 2 Error) — not HTTP status codes. Use [2] to select error spans.'
                ),
            orderBy: zod
                .enum(['timestamp', 'duration'])
                .describe('\* `timestamp` - timestamp\n\* `duration` - duration')
                .optional()
                .describe(
                    "Column to order by. Defaults to timestamp. Ordering by timestamp paginates via the keyset cursor ('after'); ordering by duration paginates via 'offset'.\n\n\* `timestamp` - timestamp\n\* `duration` - duration"
                ),
            orderDirection: zod
                .enum(['ASC', 'DESC'])
                .describe('\* `ASC` - ASC\n\* `DESC` - DESC')
                .optional()
                .describe(
                    'Order direction. Defaults to DESC (e.g. timestamp+DESC = newest first, duration+DESC = slowest first).\n\n\* `ASC` - ASC\n\* `DESC` - DESC'
                ),
            filterGroup: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .describe(
                                'Attribute key. For type \"span\", use built-in fields (trace_id, span_id, duration, name, kind, status_code, is_root_span). For \"span_attribute\"\/\"span_resource_attribute\", use the attribute key (e.g. \"http.method\").'
                            ),
                        type: zod
                            .enum(['span', 'span_attribute', 'span_resource_attribute'])
                            .describe(
                                '\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                            )
                            .describe(
                                '\"span\" filters built-in span fields. \"span_attribute\" filters span-level attributes. \"span_resource_attribute\" filters resource-level attributes.\n\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
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
                                '\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                            )
                            .describe(
                                'Comparison operator.\n\n\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                            ),
                        value: zod
                            .unknown()
                            .optional()
                            .describe(
                                'Value to compare against. String, number, or array of strings. Omit for is_set\/is_not_set operators.'
                            ),
                    })
                )
                .default(tracingSpansDurationHistogramCreateBodyQueryOneFilterGroupDefault)
                .describe('Property filters for the query.'),
            traceId: zod.string().optional().describe('Filter to a specific trace ID (hex string).'),
            limit: zod
                .number()
                .default(tracingSpansDurationHistogramCreateBodyQueryOneLimitDefault)
                .describe('Max results (1-1000). Defaults to 100.'),
            after: zod
                .string()
                .optional()
                .describe('Keyset pagination cursor from a previous timestamp-ordered response.'),
            offset: zod
                .number()
                .min(tracingSpansDurationHistogramCreateBodyQueryOneOffsetMin)
                .optional()
                .describe('Pagination offset, used when ordering by a column (e.g. duration). Defaults to 0.'),
            rootSpans: zod
                .boolean()
                .default(tracingSpansDurationHistogramCreateBodyQueryOneRootSpansDefault)
                .describe('Filter to root spans only. Defaults to true.'),
            prefetchSpans: zod.number().optional().describe('Number of child spans to prefetch per trace (1-100).'),
            excludeAttributes: zod
                .boolean()
                .default(tracingSpansDurationHistogramCreateBodyQueryOneExcludeAttributesDefault)
                .describe(
                    'Omit the per-span attributes and resource attributes maps from results to keep payloads compact. Defaults to false.'
                ),
        })
        .describe('The tracing spans query to execute.'),
})

export const tracingSpansQueryCreateBodyQueryOneFilterGroupDefault = []
export const tracingSpansQueryCreateBodyQueryOneLimitDefault = 100
export const tracingSpansQueryCreateBodyQueryOneOffsetMin = 0

export const tracingSpansQueryCreateBodyQueryOneRootSpansDefault = true
export const tracingSpansQueryCreateBodyQueryOneExcludeAttributesDefault = false

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
                    'Filter by OTel span status codes (0 Unset, 1 OK, 2 Error) — not HTTP status codes. Use [2] to select error spans.'
                ),
            orderBy: zod
                .enum(['timestamp', 'duration'])
                .describe('\* `timestamp` - timestamp\n\* `duration` - duration')
                .optional()
                .describe(
                    "Column to order by. Defaults to timestamp. Ordering by timestamp paginates via the keyset cursor ('after'); ordering by duration paginates via 'offset'.\n\n\* `timestamp` - timestamp\n\* `duration` - duration"
                ),
            orderDirection: zod
                .enum(['ASC', 'DESC'])
                .describe('\* `ASC` - ASC\n\* `DESC` - DESC')
                .optional()
                .describe(
                    'Order direction. Defaults to DESC (e.g. timestamp+DESC = newest first, duration+DESC = slowest first).\n\n\* `ASC` - ASC\n\* `DESC` - DESC'
                ),
            filterGroup: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .describe(
                                'Attribute key. For type \"span\", use built-in fields (trace_id, span_id, duration, name, kind, status_code, is_root_span). For \"span_attribute\"\/\"span_resource_attribute\", use the attribute key (e.g. \"http.method\").'
                            ),
                        type: zod
                            .enum(['span', 'span_attribute', 'span_resource_attribute'])
                            .describe(
                                '\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                            )
                            .describe(
                                '\"span\" filters built-in span fields. \"span_attribute\" filters span-level attributes. \"span_resource_attribute\" filters resource-level attributes.\n\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
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
                                '\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                            )
                            .describe(
                                'Comparison operator.\n\n\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                            ),
                        value: zod
                            .unknown()
                            .optional()
                            .describe(
                                'Value to compare against. String, number, or array of strings. Omit for is_set\/is_not_set operators.'
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
            after: zod
                .string()
                .optional()
                .describe('Keyset pagination cursor from a previous timestamp-ordered response.'),
            offset: zod
                .number()
                .min(tracingSpansQueryCreateBodyQueryOneOffsetMin)
                .optional()
                .describe('Pagination offset, used when ordering by a column (e.g. duration). Defaults to 0.'),
            rootSpans: zod
                .boolean()
                .default(tracingSpansQueryCreateBodyQueryOneRootSpansDefault)
                .describe('Filter to root spans only. Defaults to true.'),
            prefetchSpans: zod.number().optional().describe('Number of child spans to prefetch per trace (1-100).'),
            excludeAttributes: zod
                .boolean()
                .default(tracingSpansQueryCreateBodyQueryOneExcludeAttributesDefault)
                .describe(
                    'Omit the per-span attributes and resource attributes maps from results to keep payloads compact. Defaults to false.'
                ),
        })
        .describe('The tracing spans query to execute.'),
})

export const tracingSpansSparklineCreateBodyQueryOneFilterGroupDefault = []
export const tracingSpansSparklineCreateBodyQueryOneLimitDefault = 100
export const tracingSpansSparklineCreateBodyQueryOneOffsetMin = 0

export const tracingSpansSparklineCreateBodyQueryOneRootSpansDefault = true
export const tracingSpansSparklineCreateBodyQueryOneExcludeAttributesDefault = false

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
                .describe('Date range for the query. Defaults to last hour.'),
            serviceNames: zod.array(zod.string()).optional().describe('Filter by service names.'),
            statusCodes: zod
                .array(zod.number())
                .optional()
                .describe(
                    'Filter by OTel span status codes (0 Unset, 1 OK, 2 Error) — not HTTP status codes. Use [2] to select error spans.'
                ),
            orderBy: zod
                .enum(['timestamp', 'duration'])
                .describe('\* `timestamp` - timestamp\n\* `duration` - duration')
                .optional()
                .describe(
                    "Column to order by. Defaults to timestamp. Ordering by timestamp paginates via the keyset cursor ('after'); ordering by duration paginates via 'offset'.\n\n\* `timestamp` - timestamp\n\* `duration` - duration"
                ),
            orderDirection: zod
                .enum(['ASC', 'DESC'])
                .describe('\* `ASC` - ASC\n\* `DESC` - DESC')
                .optional()
                .describe(
                    'Order direction. Defaults to DESC (e.g. timestamp+DESC = newest first, duration+DESC = slowest first).\n\n\* `ASC` - ASC\n\* `DESC` - DESC'
                ),
            filterGroup: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .describe(
                                'Attribute key. For type \"span\", use built-in fields (trace_id, span_id, duration, name, kind, status_code, is_root_span). For \"span_attribute\"\/\"span_resource_attribute\", use the attribute key (e.g. \"http.method\").'
                            ),
                        type: zod
                            .enum(['span', 'span_attribute', 'span_resource_attribute'])
                            .describe(
                                '\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                            )
                            .describe(
                                '\"span\" filters built-in span fields. \"span_attribute\" filters span-level attributes. \"span_resource_attribute\" filters resource-level attributes.\n\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
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
                                '\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                            )
                            .describe(
                                'Comparison operator.\n\n\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                            ),
                        value: zod
                            .unknown()
                            .optional()
                            .describe(
                                'Value to compare against. String, number, or array of strings. Omit for is_set\/is_not_set operators.'
                            ),
                    })
                )
                .default(tracingSpansSparklineCreateBodyQueryOneFilterGroupDefault)
                .describe('Property filters for the query.'),
            traceId: zod.string().optional().describe('Filter to a specific trace ID (hex string).'),
            limit: zod
                .number()
                .default(tracingSpansSparklineCreateBodyQueryOneLimitDefault)
                .describe('Max results (1-1000). Defaults to 100.'),
            after: zod
                .string()
                .optional()
                .describe('Keyset pagination cursor from a previous timestamp-ordered response.'),
            offset: zod
                .number()
                .min(tracingSpansSparklineCreateBodyQueryOneOffsetMin)
                .optional()
                .describe('Pagination offset, used when ordering by a column (e.g. duration). Defaults to 0.'),
            rootSpans: zod
                .boolean()
                .default(tracingSpansSparklineCreateBodyQueryOneRootSpansDefault)
                .describe('Filter to root spans only. Defaults to true.'),
            prefetchSpans: zod.number().optional().describe('Number of child spans to prefetch per trace (1-100).'),
            excludeAttributes: zod
                .boolean()
                .default(tracingSpansSparklineCreateBodyQueryOneExcludeAttributesDefault)
                .describe(
                    'Omit the per-span attributes and resource attributes maps from results to keep payloads compact. Defaults to false.'
                ),
        })
        .describe('The tracing spans query to execute.'),
})

export const tracingSpansTraceCreateBodyExcludeAttributesDefault = false

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
    excludeAttributes: zod
        .boolean()
        .default(tracingSpansTraceCreateBodyExcludeAttributesDefault)
        .describe(
            'Omit the per-span attributes and resource attributes maps from results to keep payloads compact. Defaults to false.'
        ),
})

export const tracingSpansTreeCreateBodyQueryOneCompareFilterOneCompareDefault = false
export const tracingSpansTreeCreateBodyQueryOneFilterGroupDefault = []

export const TracingSpansTreeCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .object({
            spanName: zod
                .string()
                .describe(
                    'Span name to scope the matched trace set. Required because the (trace_id, parent_span_id) self-join is unsafe without bounding the matched traces.'
                ),
            serviceName: zod
                .string()
                .describe(
                    'Service name that scopes the returned tree. Applied to the spans CTE so the call-tree only contains spans from this service, even when matched traces span multiple services.'
                ),
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
                .describe('Date range for the primary window. Defaults to last hour.'),
            compareFilter: zod
                .object({
                    compare: zod
                        .boolean()
                        .default(tracingSpansTreeCreateBodyQueryOneCompareFilterOneCompareDefault)
                        .describe(
                            'When true, also fetch results for a comparison window and return them under `compare`.'
                        ),
                    compare_to: zod
                        .string()
                        .nullish()
                        .describe(
                            "Relative date offset for the comparison window (e.g. '-1h', '-1d', '-7d'). Defaults to the immediately previous period of equal length."
                        ),
                })
                .optional()
                .describe(
                    'Optional comparison-window configuration. When omitted, only the primary window is returned.'
                ),
            serviceNames: zod.array(zod.string()).optional().describe('Filter by service names.'),
            filterGroup: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .describe(
                                'Attribute key. For type \"span\", use built-in fields (trace_id, span_id, duration, name, kind, status_code, is_root_span). For \"span_attribute\"\/\"span_resource_attribute\", use the attribute key (e.g. \"http.method\").'
                            ),
                        type: zod
                            .enum(['span', 'span_attribute', 'span_resource_attribute'])
                            .describe(
                                '\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                            )
                            .describe(
                                '\"span\" filters built-in span fields. \"span_attribute\" filters span-level attributes. \"span_resource_attribute\" filters resource-level attributes.\n\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
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
                                '\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                            )
                            .describe(
                                'Comparison operator.\n\n\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
                            ),
                        value: zod
                            .unknown()
                            .optional()
                            .describe(
                                'Value to compare against. String, number, or array of strings. Omit for is_set\/is_not_set operators.'
                            ),
                    })
                )
                .default(tracingSpansTreeCreateBodyQueryOneFilterGroupDefault)
                .describe('Additional property filters applied to spans in both windows.'),
        })
        .describe('The span call-tree aggregation query to execute.'),
})
