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

/**
 * * `latest` - latest
 * `earliest` - earliest
 */
export type OrderByEnumApi = (typeof OrderByEnumApi)[keyof typeof OrderByEnumApi]

export const OrderByEnumApi = {
    Latest: 'latest',
    Earliest: 'earliest',
} as const

/**
 * * `span` - span
 * `span_attribute` - span_attribute
 * `span_resource_attribute` - span_resource_attribute
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
 * `is_not` - is_not
 * `icontains` - icontains
 * `not_icontains` - not_icontains
 * `regex` - regex
 * `not_regex` - not_regex
 * `gt` - gt
 * `lt` - lt
 * `is_set` - is_set
 * `is_not_set` - is_not_set
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
    /** Attribute key. For type "span", use built-in fields (trace_id, span_id, duration, name, kind, status_code). For "span_attribute"/"span_resource_attribute", use the attribute key (e.g. "http.method"). */
    key: string
    /** "span" filters built-in span fields. "span_attribute" filters span-level attributes. "span_resource_attribute" filters resource-level attributes.

* `span` - span
* `span_attribute` - span_attribute
* `span_resource_attribute` - span_resource_attribute */
    type: _SpanPropertyFilterTypeEnumApi
    /** Comparison operator.

* `exact` - exact
* `is_not` - is_not
* `icontains` - icontains
* `not_icontains` - not_icontains
* `regex` - regex
* `not_regex` - not_regex
* `gt` - gt
* `lt` - lt
* `is_set` - is_set
* `is_not_set` - is_not_set */
    operator: _SpanPropertyFilterOperatorEnumApi
    /** Value to compare against. String, number, or array of strings. Omit for is_set/is_not_set operators. */
    value?: unknown | null
}

export interface _TracingQueryBodyApi {
    /** Date range for the query. Defaults to last hour. */
    dateRange?: _TracingDateRangeApi
    /** Filter by service names. */
    serviceNames?: string[]
    /** Filter by HTTP status codes. */
    statusCodes?: number[]
    /** Order results by timestamp. Defaults to latest.

* `latest` - latest
* `earliest` - earliest */
    orderBy?: OrderByEnumApi
    /** Property filters for the query. */
    filterGroup?: _SpanPropertyFilterApi[]
    /** Filter to a specific trace ID (hex string). */
    traceId?: string
    /** Max results (1-1000). Defaults to 100. */
    limit?: number
    /** Pagination cursor from previous response. */
    after?: string
    /** Filter to root spans only. Defaults to true. */
    rootSpans?: boolean
    /** Number of child spans to prefetch per trace (1-100). */
    prefetchSpans?: number
}

export interface _TracingQueryRequestApi {
    /** The tracing spans query to execute. */
    query: _TracingQueryBodyApi
}

export interface _TracingTraceRequestApi {
    /** Date range for the query. Defaults to last 24 hours. */
    dateRange?: _TracingDateRangeApi
}

export type TracingSpansAttributesRetrieveParams = {
    /**
 * Type of attributes: "span" for span attributes, "resource" for resource attributes.

* `span` - span
* `resource` - resource
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
    Span: 'span',
    Resource: 'resource',
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
 * Type of attribute: "span" or "resource".

* `span` - span
* `resource` - resource
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
    Resource: 'resource',
} as const
