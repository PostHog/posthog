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
export type SpanPropertyTypeEnumApi = (typeof SpanPropertyTypeEnumApi)[keyof typeof SpanPropertyTypeEnumApi]

export const SpanPropertyTypeEnumApi = {
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
    type: SpanPropertyTypeEnumApi
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
    /** Attribute key to group by (e.g. "server.address", "http.response.status_code"). Discover keys with apm-attributes-list. For the "span" breakdown type, must be one of the allowlisted top-level columns: "service_name", "status_code". */
    breakdownKey: string
    /** Where the key lives: "span" for allowlisted top-level span columns, "span_attribute" for span-level attributes, "span_resource_attribute" for resource-level attributes.
     *
     * * `span` - span
     * * `span_attribute` - span_attribute
     * * `span_resource_attribute` - span_resource_attribute */
    breakdownType: SpanPropertyTypeEnumApi
    /** Drop filters targeting the breakdown key itself (including serviceNames for a service_name breakdown), so a facet's value list stays complete while one of its values is selected. */
    excludeBreakdownFilter?: boolean
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

export interface _TracingAttributeBreakdownRowApi {
    /** The attribute's value for this group. Spans without the attribute group under ''. */
    value: string
    /** Number of matching spans with this value. */
    count: number
    /** Number of matching error spans (status_code = 2). */
    error_count: number
    /** Median span duration in nanoseconds. */
    p50_duration_nano: number
    /** 95th percentile span duration in nanoseconds. */
    p95_duration_nano: number
}

export interface _TracingAttributeBreakdownResponseApi {
    /** One row per distinct attribute value, ordered by the requested column descending. */
    results: _TracingAttributeBreakdownRowApi[]
    /**
     * Rows for the comparison window when compareFilter.compare is true, else null.
     * @nullable
     */
    compare: _TracingAttributeBreakdownRowApi[] | null
}

/**
 * * `key` - key
 * * `value` - value
 */
export type MatchedOnEnumApi = (typeof MatchedOnEnumApi)[keyof typeof MatchedOnEnumApi]

export const MatchedOnEnumApi = {
    Key: 'key',
    Value: 'value',
} as const

export interface _TracingAttributeEntryApi {
    /** Attribute key name. */
    name: string
    /** Property filter type: "span_attribute" or "span_resource_attribute". Use this as the `type` field when filtering. */
    propertyFilterType: string
    /** How the search query matched this row: "key" if the attribute key matched, "value" if a value matched.
     *
     * * `key` - key
     * * `value` - value */
    matchedOn: MatchedOnEnumApi
    /**
     * Sample matching value — only set when matchedOn is "value".
     * @nullable
     */
    matchedValue?: string | null
}

export interface _TracingAttributesResponseApi {
    /** Available attribute keys matching the filters. */
    results: _TracingAttributeEntryApi[]
    /** Total attribute keys matched (lower bound when searching values). */
    count: number
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
    /** Number of distinct traces whose root span matches the filters — the trace count shown in the Traces view. */
    traceCount: number
}

export interface _TracingDurationHistogramQueryBodyApi {
    /** Date range for the query. Defaults to last hour. */
    dateRange?: _TracingDateRangeApi
    /** Filter by service names. */
    serviceNames?: string[]
    /** Filter by OTel span status codes (0 Unset, 1 OK, 2 Error) — not HTTP status codes. Use [2] to select error spans. */
    statusCodes?: number[]
    /** Property filters for the query. */
    filterGroup?: _SpanPropertyFilterApi[]
    /** When true (default), bucket root-span durations only — a distribution of traces. When false, bucket every matching span — used with a span name filter for operation-scoped distributions. */
    rootSpans?: boolean
}

export interface _TracingDurationHistogramRequestApi {
    /** The duration-histogram query to execute. */
    query: _TracingDurationHistogramQueryBodyApi
}

export interface _HasSpansResponseApi {
    /** Whether the team has ingested any tracing spans yet. Used to gate the onboarding empty state. */
    hasSpans: boolean
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
    /** Return the matching spans themselves, one row per span (root and child), instead of collapsing to traces. Use this to search by a child-span attribute (e.g. code.filepath) without the whole-trace grouping. Distinct from rootSpans. Defaults to false. */
    flatSpans?: boolean
    /** Number of child spans to prefetch per trace (1-100). */
    prefetchSpans?: number
    /** Omit the per-span attributes and resource attributes maps from results to keep payloads compact. Defaults to false. */
    excludeAttributes?: boolean
}

export interface _TracingQueryRequestApi {
    /** The tracing spans query to execute. */
    query: _TracingQueryBodyApi
}

export interface _TracingSparklineQueryBodyApi {
    /** Date range for the query. Defaults to last hour. */
    dateRange?: _TracingDateRangeApi
    /** Filter by service names. */
    serviceNames?: string[]
    /** Filter by OTel span status codes (0 Unset, 1 OK, 2 Error) — not HTTP status codes. Use [2] to select error spans. */
    statusCodes?: number[]
    /** Property filters for the query. */
    filterGroup?: _SpanPropertyFilterApi[]
    /** When true, count only root spans (one per trace) so the bars reflect the Traces view. When false (default), count every matching span — the Spans view's volume. */
    rootSpans?: boolean
}

export interface _TracingSparklineRequestApi {
    /** The sparkline query to execute. */
    query: _TracingSparklineQueryBodyApi
}

export interface _SymbolStatsSymbolApi {
    /**
     * Opaque identifier (e.g. the function name) echoed back on the matching result row.
     * @nullable
     */
    name?: string | null
    /**
     * First line of the symbol's range, inclusive.
     * @minimum 1
     */
    startLine: number
    /**
     * Last line of the symbol's range, inclusive.
     * @minimum 1
     */
    endLine: number
}

export interface _SymbolStatsQueryBodyApi {
    /** Repo-relative path of the source file to aggregate (e.g. 'src/flags/flag_matching.rs'). Matched as a path suffix against the recorded OTel code.file.path / code.filepath, so a recorded path carrying an extra crate/workspace prefix still matches. Separators are normalized. */
    filePath: string
    /** Current period to aggregate over; the prior equal-length window is the comparison. Defaults to last 24h. */
    dateRange?: _TracingDateRangeApi
    /** Optional symbol (function) line ranges, supplied by the client from its own AST/LSP. When given, each span is attributed to the smallest enclosing range (one row per symbol). When omitted (or an empty list), spans are aggregated per source line (one row per line); pass a single whole-file range for a file-level total. */
    symbols?: _SymbolStatsSymbolApi[]
}

export interface _SymbolStatsRequestApi {
    /** The symbol-stats per-symbol aggregation query to execute. */
    query: _SymbolStatsQueryBodyApi
}

export interface _SymbolStatsPeriodApi {
    /** Number of spans attributed to this symbol in the period. */
    count: number
    /** Spans whose OTel status is Error (status_code = 2). */
    error_count: number
    /** Total wall-clock span duration in the period, in nanoseconds (additive across spans). */
    sum_duration_nano: number
    /** Median wall-clock span duration, in nanoseconds. */
    p50_duration_nano: number
    /** 95th-percentile wall-clock span duration, in nanoseconds. */
    p95_duration_nano: number
    /** 99th-percentile wall-clock span duration, in nanoseconds. */
    p99_duration_nano: number
    /** Spans in the period carrying an active/busy time attribute. 0 means busy_* are not meaningful. */
    busy_count: number
    /** Median active (busy) time, in nanoseconds. Excludes awaiting children. */
    p50_busy_nano: number
    /** 95th-percentile active (busy) time, in nanoseconds. */
    p95_busy_nano: number
    /** 99th-percentile active (busy) time, in nanoseconds. */
    p99_busy_nano: number
}

export interface _SymbolStatsRowApi {
    /** Number of spans attributed to this symbol in the period. */
    count: number
    /** Spans whose OTel status is Error (status_code = 2). */
    error_count: number
    /** Total wall-clock span duration in the period, in nanoseconds (additive across spans). */
    sum_duration_nano: number
    /** Median wall-clock span duration, in nanoseconds. */
    p50_duration_nano: number
    /** 95th-percentile wall-clock span duration, in nanoseconds. */
    p95_duration_nano: number
    /** 99th-percentile wall-clock span duration, in nanoseconds. */
    p99_duration_nano: number
    /** Spans in the period carrying an active/busy time attribute. 0 means busy_* are not meaningful. */
    busy_count: number
    /** Median active (busy) time, in nanoseconds. Excludes awaiting children. */
    p50_busy_nano: number
    /** 95th-percentile active (busy) time, in nanoseconds. */
    p95_busy_nano: number
    /** 99th-percentile active (busy) time, in nanoseconds. */
    p99_busy_nano: number
    /** Bucket anchor: the source line (line mode) or the symbol's startLine (symbol mode). */
    line: number
    /**
     * Echoed name from the requested symbol (symbol mode only).
     * @nullable
     */
    name?: string | null
    /**
     * endLine of the matched symbol's range (symbol mode only).
     * @nullable
     */
    end_line?: number | null
    /** The same metrics over the immediately-preceding equal-length period. */
    previous: _SymbolStatsPeriodApi
    /**
     * Percentage change in count vs the previous period (180 = +180%). Null when there is no baseline (previous count 0). Use `previous.count` — not a null here — to detect a new symbol.
     * @nullable
     */
    count_pct_change: number | null
    /**
     * Percentage change in p95 duration vs the previous period (180 = +180%). Null when the previous p95 is 0 (no comparable baseline), which can occur even when previous.count > 0 — do not read null as 'new symbol'.
     * @nullable
     */
    p95_duration_pct_change: number | null
}

/**
 * * `line` - line
 * * `symbol` - symbol
 */
export type GranularityEnumApi = (typeof GranularityEnumApi)[keyof typeof GranularityEnumApi]

export const GranularityEnumApi = {
    Line: 'line',
    Symbol: 'symbol',
} as const

export interface _SymbolStatsResponseApi {
    /** One row per bucket, ordered by line ascending. */
    results: _SymbolStatsRowApi[]
    /** Bucketing applied: 'line' when no symbols were supplied, 'symbol' otherwise.
     *
     * * `line` - line
     * * `symbol` - symbol */
    granularity: GranularityEnumApi
}

export interface _TracingTraceRequestApi {
    /** Date range for the query. Defaults to last 24 hours. */
    dateRange?: _TracingDateRangeApi
    /** Omit the per-span attributes and resource attributes maps from results to keep payloads compact. Defaults to false. */
    excludeAttributes?: boolean
    /**
     * Pagination offset into the trace's spans (ordered by start time ascending). Each page returns up to 2000 spans; pass the response's `nextOffset` to load the next page. Defaults to 0.
     * @minimum 0
     */
    offset?: number
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

/**
 * * `engineering` - Engineering
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
}

/**
 * Saved tracing filters — a subset of the frontend TracingFilters shape. May contain dateRange, serviceNames, filterGroup, orderBy, orderDirection, and viewMode.
 */
export type TracingViewApiFilters = { [key: string]: unknown }

export interface TracingViewApi {
    readonly id: string
    readonly short_id: string
    /**
     * Human-readable name shown in the saved views list.
     * @maxLength 400
     */
    name: string
    /** Saved tracing filters — a subset of the frontend TracingFilters shape. May contain dateRange, serviceNames, filterGroup, orderBy, orderDirection, and viewMode. */
    filters?: TracingViewApiFilters
    /** Whether the view is pinned for quick access. */
    pinned?: boolean
    readonly created_at: string
    /** User who created the view. */
    readonly created_by: UserBasicApi | null
    /** @nullable */
    readonly updated_at: string | null
}

export interface PaginatedTracingViewListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: TracingViewApi[]
}

/**
 * Saved tracing filters — a subset of the frontend TracingFilters shape. May contain dateRange, serviceNames, filterGroup, orderBy, orderDirection, and viewMode.
 */
export type PatchedTracingViewApiFilters = { [key: string]: unknown }

export interface PatchedTracingViewApi {
    readonly id?: string
    readonly short_id?: string
    /**
     * Human-readable name shown in the saved views list.
     * @maxLength 400
     */
    name?: string
    /** Saved tracing filters — a subset of the frontend TracingFilters shape. May contain dateRange, serviceNames, filterGroup, orderBy, orderDirection, and viewMode. */
    filters?: PatchedTracingViewApiFilters
    /** Whether the view is pinned for quick access. */
    pinned?: boolean
    readonly created_at?: string
    /** User who created the view. */
    readonly created_by?: UserBasicApi | null
    /** @nullable */
    readonly updated_at?: string | null
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
    /**
     * When true, the search query also matches attribute values (not just keys), so a value such as a trace_id finds the key holding it.
     */
    search_values?: boolean
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

export type TracingViewsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
