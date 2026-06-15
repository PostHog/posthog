/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface _TracingDateRangeApi {
    /**
     * Start of the date range. Accepts ISO 8601 timestamps or relative formats: -1h, -6h, -1d, -7d, etc.
     * @nullable
     */
    date_from?: string | null
    /**
     * End of the date range. Same format as date_from. Omit or null for "now".
     * @nullable
     */
    date_to?: string | null
}

export interface _CompareFilterApi {
    /** When true, also fetch results for a comparison window and return them under `compare`. */
    compare?: boolean
    /**
     * Relative date offset for the comparison window (e.g. '-1h', '-1d', '-7d'). Defaults to the immediately previous period of equal length.
     * @nullable
     */
    compare_to?: string | null
}

/**
 * * `span` - span
 * * `span_attribute` - span_attribute
 * * `span_resource_attribute` - span_resource_attribute
 */
export type _SpanPropertyFilterTypeEnumApi =
    (typeof _SpanPropertyFilterTypeEnumApi)[keyof typeof _SpanPropertyFilterTypeEnumApi]

export const _SpanPropertyFilterTypeEnumApi = {
    Span: 'span',
    SpanAttribute: 'span_attribute',
    SpanResourceAttribute: 'span_resource_attribute',
} as const

/**
 * * `exact` - exact
 * * `is_not` - is_not
 * * `icontains` - icontains
 * * `not_icontains` - not_icontains
 * * `regex` - regex
 * * `not_regex` - not_regex
 * * `gt` - gt
 * * `lt` - lt
 * * `is_set` - is_set
 * * `is_not_set` - is_not_set
 */
export type _SpanPropertyFilterOperatorEnumApi =
    (typeof _SpanPropertyFilterOperatorEnumApi)[keyof typeof _SpanPropertyFilterOperatorEnumApi]

export const _SpanPropertyFilterOperatorEnumApi = {
    Exact: 'exact',
    IsNot: 'is_not',
    Icontains: 'icontains',
    NotIcontains: 'not_icontains',
    Regex: 'regex',
    NotRegex: 'not_regex',
    Gt: 'gt',
    Lt: 'lt',
    IsSet: 'is_set',
    IsNotSet: 'is_not_set',
} as const

export interface _SpanPropertyFilterApi {
    /** Attribute key. For type "span", use built-in fields (trace_id, span_id, duration, name, kind, status_code, is_root_span). For "span_attribute"/"span_resource_attribute", use the attribute key (e.g. "http.method"). */
    key: string
    /** "span" filters built-in span fields. "span_attribute" filters span-level attributes. "span_resource_attribute" filters resource-level attributes.
     *
     * * `span` - span
     * * `span_attribute` - span_attribute
     * * `span_resource_attribute` - span_resource_attribute */
    type: _SpanPropertyFilterTypeEnumApi
    /** Comparison operator.
     *
     * * `exact` - exact
     * * `is_not` - is_not
     * * `icontains` - icontains
     * * `not_icontains` - not_icontains
     * * `regex` - regex
     * * `not_regex` - not_regex
     * * `gt` - gt
     * * `lt` - lt
     * * `is_set` - is_set
     * * `is_not_set` - is_not_set */
    operator: _SpanPropertyFilterOperatorEnumApi
    /** Value to compare against. String, number, or array of strings. Omit for is_set/is_not_set operators. */
    value?: unknown
}

export interface _TracingAggregationQueryBodyApi {
    /** Date range for the primary window. Defaults to last hour. */
    dateRange?: _TracingDateRangeApi
    /** Optional comparison-window configuration. When omitted, only the primary window is returned. */
    compareFilter?: _CompareFilterApi
    /** Filter by service names. */
    serviceNames?: string[]
    /** Property filters applied to spans in both windows. */
    filterGroup?: _SpanPropertyFilterApi[]
}

export interface _TracingAggregationRequestApi {
    /** The span aggregation query to execute. */
    query: _TracingAggregationQueryBodyApi
}

/**
 * * `span_attribute` - span_attribute
 * * `span_resource_attribute` - span_resource_attribute
 */
export type BreakdownTypeEnumApi = (typeof BreakdownTypeEnumApi)[keyof typeof BreakdownTypeEnumApi]

export const BreakdownTypeEnumApi = {
    SpanAttribute: 'span_attribute',
    SpanResourceAttribute: 'span_resource_attribute',
} as const

/**
 * * `count` - count
 * * `error_count` - error_count
 */
export type _TracingAttributeBreakdownQueryBodyOrderByEnumApi =
    (typeof _TracingAttributeBreakdownQueryBodyOrderByEnumApi)[keyof typeof _TracingAttributeBreakdownQueryBodyOrderByEnumApi]

export const _TracingAttributeBreakdownQueryBodyOrderByEnumApi = {
    Count: 'count',
    ErrorCount: 'error_count',
} as const

export interface _TracingAttributeBreakdownQueryBodyApi {
    /** Attribute key to group by (e.g. "server.address", "http.response.status_code"). Discover keys with apm-attributes-list. */
    breakdownKey: string
    /** Where the key lives: "span_attribute" for span-level attributes, "span_resource_attribute" for resource-level attributes.
     *
     * * `span_attribute` - span_attribute
     * * `span_resource_attribute` - span_resource_attribute */
    breakdownType: BreakdownTypeEnumApi
    /** Order rows by span count or error count, descending. Defaults to count.
     *
     * * `count` - count
     * * `error_count` - error_count */
    orderBy?: _TracingAttributeBreakdownQueryBodyOrderByEnumApi
    /** Date range for the primary window. Defaults to last hour. */
    dateRange?: _TracingDateRangeApi
    /** Optional comparison-window configuration. When omitted, only the primary window is returned. */
    compareFilter?: _CompareFilterApi
    /** Filter by service names. */
    serviceNames?: string[]
    /** Property filters scoping the spans the breakdown runs over (e.g. only error spans). */
    filterGroup?: _SpanPropertyFilterApi[]
}

export interface _TracingAttributeBreakdownRequestApi {
    /** The attribute breakdown query to execute. */
    query: _TracingAttributeBreakdownQueryBodyApi
}

export interface _TracingCountBodyApi {
    /** Date range for the count. Defaults to last hour. */
    dateRange?: _TracingDateRangeApi
    /** Filter by service names. */
    serviceNames?: string[]
    /** Filter by OTel span status codes (0 Unset, 1 OK, 2 Error) — not HTTP status codes. Use [2] to select error spans. */
    statusCodes?: number[]
    /** Property filters for the count. */
    filterGroup?: _SpanPropertyFilterApi[]
}

export interface _TracingCountRequestApi {
    /** The span count query to execute. */
    query: _TracingCountBodyApi
}

export interface _TracingCountResponseApi {
    /** Number of spans matching the filters. */
    count: number
}

/**
 * * `timestamp` - timestamp
 * * `duration` - duration
 */
export type _TracingQueryBodyOrderByEnumApi =
    (typeof _TracingQueryBodyOrderByEnumApi)[keyof typeof _TracingQueryBodyOrderByEnumApi]

export const _TracingQueryBodyOrderByEnumApi = {
    Timestamp: 'timestamp',
    Duration: 'duration',
} as const

/**
 * * `ASC` - ASC
 * * `DESC` - DESC
 */
export type OrderDirectionEnumApi = (typeof OrderDirectionEnumApi)[keyof typeof OrderDirectionEnumApi]

export const OrderDirectionEnumApi = {
    Asc: 'ASC',
    Desc: 'DESC',
} as const

export interface _TracingQueryBodyApi {
    /** Date range for the query. Defaults to last hour. */
    dateRange?: _TracingDateRangeApi
    /** Filter by service names. */
    serviceNames?: string[]
    /** Filter by OTel span status codes (0 Unset, 1 OK, 2 Error) — not HTTP status codes. Use [2] to select error spans. */
    statusCodes?: number[]
    /** Column to order by. Defaults to timestamp. Ordering by timestamp paginates via the keyset cursor ('after'); ordering by duration paginates via 'offset'.
     *
     * * `timestamp` - timestamp
     * * `duration` - duration */
    orderBy?: _TracingQueryBodyOrderByEnumApi
    /** Order direction. Defaults to DESC (e.g. timestamp+DESC = newest first, duration+DESC = slowest first).
     *
     * * `ASC` - ASC
     * * `DESC` - DESC */
    orderDirection?: OrderDirectionEnumApi
    /** Property filters for the query. */
    filterGroup?: _SpanPropertyFilterApi[]
    /** Filter to a specific trace ID (hex string). */
    traceId?: string
    /** Max results (1-1000). Defaults to 100. */
    limit?: number
    /** Keyset pagination cursor from a previous timestamp-ordered response. */
    after?: string
    /**
     * Pagination offset, used when ordering by a column (e.g. duration). Defaults to 0.
     * @minimum 0
     */
    offset?: number
    /** Filter to root spans only. Defaults to true. */
    rootSpans?: boolean
    /** Number of child spans to prefetch per trace (1-100). */
    prefetchSpans?: number
    /** Omit the per-span attributes and resource attributes maps from results to keep payloads compact. Defaults to false. */
    excludeAttributes?: boolean
}

export interface _TracingQueryRequestApi {
    /** The tracing spans query to execute. */
    query: _TracingQueryBodyApi
}

export interface _HasSpansResponseApi {
    /** Whether the team has ingested any tracing spans yet. Used to gate the onboarding empty state. */
    hasSpans: boolean
}

export interface _TracingTraceRequestApi {
    /** Date range for the query. Defaults to last 24 hours. */
    dateRange?: _TracingDateRangeApi
    /** Omit the per-span attributes and resource attributes maps from results to keep payloads compact. Defaults to false. */
    excludeAttributes?: boolean
}

export interface _TracingTreeQueryBodyApi {
    /** Span name to scope the matched trace set. Required because the (trace_id, parent_span_id) self-join is unsafe without bounding the matched traces. */
    spanName: string
    /** Service name that scopes the returned tree. Applied to the spans CTE so the call-tree only contains spans from this service, even when matched traces span multiple services. */
    serviceName: string
    /** Date range for the primary window. Defaults to last hour. */
    dateRange?: _TracingDateRangeApi
    /** Optional comparison-window configuration. When omitted, only the primary window is returned. */
    compareFilter?: _CompareFilterApi
    /** Filter by service names. */
    serviceNames?: string[]
    /** Additional property filters applied to spans in both windows. */
    filterGroup?: _SpanPropertyFilterApi[]
}

export interface _TracingTreeRequestApi {
    /** The span call-tree aggregation query to execute. */
    query: _TracingTreeQueryBodyApi
}

export type TracingSpansAttributesRetrieveParams = {
    /**
     * Type of attributes: "span_attribute" for span-level attributes, "span_resource_attribute" for resource-level attributes.
     *
     * * `span_attribute` - span_attribute
     * * `span_resource_attribute` - span_resource_attribute
     * @minLength 1
     */
    attribute_type?: TracingSpansAttributesRetrieveAttributeType
    /**
     * Max results (default: 100).
     * @minimum 1
     * @maximum 100
     */
    limit?: number
    /**
     * Pagination offset (default: 0).
     * @minimum 0
     */
    offset?: number
    /**
     * Search filter for attribute names.
     * @minLength 1
     */
    search?: string
}

export type TracingSpansAttributesRetrieveAttributeType =
    (typeof TracingSpansAttributesRetrieveAttributeType)[keyof typeof TracingSpansAttributesRetrieveAttributeType]

export const TracingSpansAttributesRetrieveAttributeType = {
    SpanAttribute: 'span_attribute',
    SpanResourceAttribute: 'span_resource_attribute',
} as const

export type TracingSpansServiceNamesRetrieveParams = {
    /**
     * JSON-encoded date range, e.g. '{"date_from": "-1h"}'.
     * @minLength 1
     */
    dateRange?: string
    /**
     * Search filter for service names.
     * @minLength 1
     */
    search?: string
}

export type TracingSpansValuesRetrieveParams = {
    /**
     * Type of attribute: "span" for built-in span fields (e.g. name), "span_attribute" for span-level attributes, "span_resource_attribute" for resource-level attributes.
     *
     * * `span` - span
     * * `span_attribute` - span_attribute
     * * `span_resource_attribute` - span_resource_attribute
     * @minLength 1
     */
    attribute_type?: TracingSpansValuesRetrieveAttributeType
    /**
     * The attribute key to get values for.
     * @minLength 1
     */
    key: string
    /**
     * Max results (default: 100).
     * @minimum 1
     * @maximum 100
     */
    limit?: number
    /**
     * Pagination offset (default: 0).
     * @minimum 0
     */
    offset?: number
    /**
     * Search filter for attribute values.
     * @minLength 1
     */
    value?: string
}

export type TracingSpansValuesRetrieveAttributeType =
    (typeof TracingSpansValuesRetrieveAttributeType)[keyof typeof TracingSpansValuesRetrieveAttributeType]

export const TracingSpansValuesRetrieveAttributeType = {
    Span: 'span',
    SpanAttribute: 'span_attribute',
    SpanResourceAttribute: 'span_resource_attribute',
} as const
