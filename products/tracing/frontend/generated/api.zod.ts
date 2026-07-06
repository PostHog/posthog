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
            personId: zod
                .string()
                .optional()
                .describe(
                    "Show spans for a given person (person UUID). Expanded server-side to the person's distinct IDs and matched against the team's configured distinct-id span attribute (see the tracing_config endpoint; defaults to 'posthogDistinctId')."
                ),
        })
        .describe('The span aggregation query to execute.'),
})

export const tracingSpansAttributeBreakdownCreateBodyQueryOneCompareFilterOneCompareDefault = false
export const tracingSpansAttributeBreakdownCreateBodyQueryOneFilterGroupDefault = []

export const TracingSpansAttributeBreakdownCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .object({
            breakdownKey: zod
                .string()
                .describe(
                    'Attribute key to group by (e.g. \"server.address\", \"http.response.status_code\"). Discover keys with apm-attributes-list.'
                ),
            breakdownType: zod
                .enum(['span_attribute', 'span_resource_attribute'])
                .describe(
                    '\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                )
                .describe(
                    'Where the key lives: \"span_attribute\" for span-level attributes, \"span_resource_attribute\" for resource-level attributes.\n\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
                ),
            orderBy: zod
                .enum(['count', 'error_count'])
                .describe('\* `count` - count\n\* `error_count` - error_count')
                .optional()
                .describe(
                    'Order rows by span count or error count, descending. Defaults to count.\n\n\* `count` - count\n\* `error_count` - error_count'
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
                        .default(tracingSpansAttributeBreakdownCreateBodyQueryOneCompareFilterOneCompareDefault)
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
                .default(tracingSpansAttributeBreakdownCreateBodyQueryOneFilterGroupDefault)
                .describe('Property filters scoping the spans the breakdown runs over (e.g. only error spans).'),
            personId: zod
                .string()
                .optional()
                .describe(
                    "Show spans for a given person (person UUID). Expanded server-side to the person's distinct IDs and matched against the team's configured distinct-id span attribute (see the tracing_config endpoint; defaults to 'posthogDistinctId')."
                ),
        })
        .describe('The attribute breakdown query to execute.'),
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
            personId: zod
                .string()
                .optional()
                .describe(
                    "Show spans for a given person (person UUID). Expanded server-side to the person's distinct IDs and matched against the team's configured distinct-id span attribute (see the tracing_config endpoint; defaults to 'posthogDistinctId')."
                ),
        })
        .describe('The span count query to execute.'),
})

export const tracingSpansDurationHistogramCreateBodyQueryOneFilterGroupDefault = []
export const tracingSpansDurationHistogramCreateBodyQueryOneRootSpansDefault = true

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
            personId: zod
                .string()
                .optional()
                .describe(
                    "Show spans for a given person (person UUID). Expanded server-side to the person's distinct IDs and matched against the team's configured distinct-id span attribute (see the tracing_config endpoint; defaults to 'posthogDistinctId')."
                ),
            rootSpans: zod
                .boolean()
                .default(tracingSpansDurationHistogramCreateBodyQueryOneRootSpansDefault)
                .describe(
                    'When true (default), bucket root-span durations only — a distribution of traces. When false, bucket every matching span — used with a span name filter for operation-scoped distributions.'
                ),
        })
        .describe('The duration-histogram query to execute.'),
})

export const tracingSpansQueryCreateBodyQueryOneFilterGroupDefault = []
export const tracingSpansQueryCreateBodyQueryOneLimitDefault = 100
export const tracingSpansQueryCreateBodyQueryOneOffsetMin = 0

export const tracingSpansQueryCreateBodyQueryOneRootSpansDefault = true
export const tracingSpansQueryCreateBodyQueryOneFlatSpansDefault = false
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
            flatSpans: zod
                .boolean()
                .default(tracingSpansQueryCreateBodyQueryOneFlatSpansDefault)
                .describe(
                    'Return the matching spans themselves, one row per span (root and child), instead of collapsing to traces. Use this to search by a child-span attribute (e.g. code.filepath) without the whole-trace grouping. Distinct from rootSpans. Defaults to false.'
                ),
            prefetchSpans: zod.number().optional().describe('Number of child spans to prefetch per trace (1-100).'),
            excludeAttributes: zod
                .boolean()
                .default(tracingSpansQueryCreateBodyQueryOneExcludeAttributesDefault)
                .describe(
                    'Omit the per-span attributes and resource attributes maps from results to keep payloads compact. Defaults to false.'
                ),
            personId: zod
                .string()
                .optional()
                .describe(
                    "Show spans for a given person (person UUID). Expanded server-side to the person's distinct IDs and matched against the team's configured distinct-id span attribute (see the tracing_config endpoint; defaults to 'posthogDistinctId')."
                ),
        })
        .describe('The tracing spans query to execute.'),
})

export const tracingSpansSparklineCreateBodyQueryOneFilterGroupDefault = []
export const tracingSpansSparklineCreateBodyQueryOneRootSpansDefault = false

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
            personId: zod
                .string()
                .optional()
                .describe(
                    "Show spans for a given person (person UUID). Expanded server-side to the person's distinct IDs and matched against the team's configured distinct-id span attribute (see the tracing_config endpoint; defaults to 'posthogDistinctId')."
                ),
            rootSpans: zod
                .boolean()
                .default(tracingSpansSparklineCreateBodyQueryOneRootSpansDefault)
                .describe(
                    "When true, count only root spans (one per trace) so the bars reflect the Traces view. When false (default), count every matching span — the Spans view's volume."
                ),
        })
        .describe('The sparkline query to execute.'),
})

export const TracingSpansSymbolStatsCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .object({
            filePath: zod
                .string()
                .describe(
                    "Repo-relative path of the source file to aggregate (e.g. 'src\/flags\/flag_matching.rs'). Matched as a path suffix against the recorded OTel code.file.path \/ code.filepath, so a recorded path carrying an extra crate\/workspace prefix still matches. Separators are normalized."
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
                .describe(
                    'Current period to aggregate over; the prior equal-length window is the comparison. Defaults to last 24h.'
                ),
            symbols: zod
                .array(
                    zod.object({
                        name: zod
                            .string()
                            .nullish()
                            .describe(
                                'Opaque identifier (e.g. the function name) echoed back on the matching result row.'
                            ),
                        startLine: zod.number().min(1).describe("First line of the symbol's range, inclusive."),
                        endLine: zod.number().min(1).describe("Last line of the symbol's range, inclusive."),
                    })
                )
                .optional()
                .describe(
                    'Optional symbol (function) line ranges, supplied by the client from its own AST\/LSP. When given, each span is attributed to the smallest enclosing range (one row per symbol). When omitted (or an empty list), spans are aggregated per source line (one row per line); pass a single whole-file range for a file-level total.'
                ),
        })
        .describe('The symbol-stats per-symbol aggregation query to execute.'),
})

export const tracingSpansTraceCreateBodyExcludeAttributesDefault = false
export const tracingSpansTraceCreateBodyOffsetMin = 0

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
    offset: zod
        .number()
        .min(tracingSpansTraceCreateBodyOffsetMin)
        .optional()
        .describe(
            "Pagination offset into the trace's spans (ordered by start time ascending). Each page returns up to 2000 spans; pass the response's `nextOffset` to load the next page. Defaults to 0."
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
            personId: zod
                .string()
                .optional()
                .describe(
                    "Show spans for a given person (person UUID). Expanded server-side to the person's distinct IDs and matched against the team's configured distinct-id span attribute (see the tracing_config endpoint; defaults to 'posthogDistinctId')."
                ),
        })
        .describe('The span call-tree aggregation query to execute.'),
})

export const tracingViewsCreateBodyNameMax = 400

export const TracingViewsCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(tracingViewsCreateBodyNameMax)
        .describe('Human-readable name shown in the saved views list.'),
    filters: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Saved tracing filters — a subset of the frontend TracingFilters shape. May contain dateRange, serviceNames, filterGroup, orderBy, orderDirection, and viewMode.'
        ),
    pinned: zod.boolean().optional().describe('Whether the view is pinned for quick access.'),
})

export const tracingViewsUpdateBodyNameMax = 400

export const TracingViewsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(tracingViewsUpdateBodyNameMax)
        .describe('Human-readable name shown in the saved views list.'),
    filters: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Saved tracing filters — a subset of the frontend TracingFilters shape. May contain dateRange, serviceNames, filterGroup, orderBy, orderDirection, and viewMode.'
        ),
    pinned: zod.boolean().optional().describe('Whether the view is pinned for quick access.'),
})

export const tracingViewsPartialUpdateBodyNameMax = 400

export const TracingViewsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(tracingViewsPartialUpdateBodyNameMax)
        .optional()
        .describe('Human-readable name shown in the saved views list.'),
    filters: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Saved tracing filters — a subset of the frontend TracingFilters shape. May contain dateRange, serviceNames, filterGroup, orderBy, orderDirection, and viewMode.'
        ),
    pinned: zod.boolean().optional().describe('Whether the view is pinned for quick access.'),
})
