/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 5 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const TracingSpansAttributesRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const tracingSpansAttributesRetrieveQueryLimitMax = 100

export const tracingSpansAttributesRetrieveQueryOffsetMin = 0

export const TracingSpansAttributesRetrieveQueryParams = /* @__PURE__ */ zod.object({
    attribute_type: zod
        .enum(['span', 'resource'])
        .optional()
        .describe(
            'Type of attributes: "span" for span attributes, "resource" for resource attributes.\n\n* `span` - span\n* `resource` - resource'
        ),
    limit: zod
        .number()
        .min(1)
        .max(tracingSpansAttributesRetrieveQueryLimitMax)
        .optional()
        .describe('Max results (default: 100).'),
    offset: zod
        .number()
        .min(tracingSpansAttributesRetrieveQueryOffsetMin)
        .optional()
        .describe('Pagination offset (default: 0).'),
    search: zod.string().min(1).optional().describe('Search filter for attribute names.'),
})

export const TracingSpansQueryCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
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
                        .describe('End of the date range. Same format as date_from. Omit or null for "now".'),
                })
                .optional()
                .describe('Date range for the query. Defaults to last hour.'),
            serviceNames: zod.array(zod.string()).optional().describe('Filter by service names.'),
            statusCodes: zod.array(zod.number()).optional().describe('Filter by HTTP status codes.'),
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
                                'Attribute key. For type "span", use built-in fields (trace_id, span_id, duration, name, kind, status_code). For "span_attribute"/"span_resource_attribute", use the attribute key (e.g. "http.method").'
                            ),
                        type: zod
                            .enum(['span', 'span_attribute', 'span_resource_attribute'])
                            .describe(
                                '* `span` - span\n* `span_attribute` - span_attribute\n* `span_resource_attribute` - span_resource_attribute'
                            )
                            .describe(
                                '"span" filters built-in span fields. "span_attribute" filters span-level attributes. "span_resource_attribute" filters resource-level attributes.\n\n* `span` - span\n* `span_attribute` - span_attribute\n* `span_resource_attribute` - span_resource_attribute'
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

export const TracingSpansServiceNamesRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const TracingSpansServiceNamesRetrieveQueryParams = /* @__PURE__ */ zod.object({
    dateRange: zod.string().min(1).optional().describe('JSON-encoded date range, e.g. \'{"date_from": "-1h"}\'.'),
    search: zod.string().min(1).optional().describe('Search filter for service names.'),
})

export const tracingSpansTraceCreatePathTraceIdRegExp = new RegExp('^[a-zA-Z0-9]+$')

export const TracingSpansTraceCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    trace_id: zod.string().regex(tracingSpansTraceCreatePathTraceIdRegExp),
})

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
                .describe('End of the date range. Same format as date_from. Omit or null for "now".'),
        })
        .optional()
        .describe('Date range for the query. Defaults to last 24 hours.'),
})

export const TracingSpansValuesRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const tracingSpansValuesRetrieveQueryLimitMax = 100

export const tracingSpansValuesRetrieveQueryOffsetMin = 0

export const TracingSpansValuesRetrieveQueryParams = /* @__PURE__ */ zod.object({
    attribute_type: zod
        .enum(['span', 'resource'])
        .optional()
        .describe('Type of attribute: "span" or "resource".\n\n* `span` - span\n* `resource` - resource'),
    key: zod.string().min(1).describe('The attribute key to get values for.'),
    limit: zod
        .number()
        .min(1)
        .max(tracingSpansValuesRetrieveQueryLimitMax)
        .optional()
        .describe('Max results (default: 100).'),
    offset: zod
        .number()
        .min(tracingSpansValuesRetrieveQueryOffsetMin)
        .optional()
        .describe('Pagination offset (default: 0).'),
    value: zod.string().min(1).optional().describe('Search filter for attribute values.'),
})
