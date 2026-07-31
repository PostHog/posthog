/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const _TracingDateRangeApi = zod.object({
    date_from: zod
        .string()
        .nullish()
        .describe('Start of the date range. Accepts ISO 8601 timestamps or relative formats: -1h, -6h, -1d, -7d, etc.'),
    date_to: zod
        .string()
        .nullish()
        .describe('End of the date range. Same format as date_from. Omit or null for \"now\".'),
})

export type _TracingDateRangeApi = zod.input<typeof _TracingDateRangeApi>
export type _TracingDateRangeApiOutput = zod.output<typeof _TracingDateRangeApi>

export const _compareFilterApiCompareDefault = false

export const _CompareFilterApi = zod.object({
    compare: zod
        .boolean()
        .default(_compareFilterApiCompareDefault)
        .describe('When true, also fetch results for a comparison window and return them under `compare`.'),
    compare_to: zod
        .string()
        .nullish()
        .describe(
            "Relative date offset for the comparison window (e.g. '-1h', '-1d', '-7d'). Defaults to the immediately previous period of equal length."
        ),
})

export type _CompareFilterApi = zod.input<typeof _CompareFilterApi>
export type _CompareFilterApiOutput = zod.output<typeof _CompareFilterApi>

export const SpanPropertyTypeEnumApi = zod
    .enum(['span', 'span_attribute', 'span_resource_attribute'])
    .describe(
        '\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
    )

export type SpanPropertyTypeEnumApi = zod.input<typeof SpanPropertyTypeEnumApi>
export type SpanPropertyTypeEnumApiOutput = zod.output<typeof SpanPropertyTypeEnumApi>

export const _SpanPropertyFilterOperatorEnumApi = zod
    .enum([
        'exact',
        'is_not',
        'icontains',
        'not_icontains',
        'starts_with',
        'not_starts_with',
        'ends_with',
        'not_ends_with',
        'regex',
        'not_regex',
        'gt',
        'lt',
        'is_set',
        'is_not_set',
    ])
    .describe(
        '\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
    )

export type _SpanPropertyFilterOperatorEnumApi = zod.input<typeof _SpanPropertyFilterOperatorEnumApi>
export type _SpanPropertyFilterOperatorEnumApiOutput = zod.output<typeof _SpanPropertyFilterOperatorEnumApi>

export const _SpanPropertyFilterApi = zod.object({
    key: zod
        .string()
        .describe(
            'Attribute key. For type \"span\", use built-in fields (trace_id, span_id, duration, name, kind, status_code, is_root_span). For \"span_attribute\"\/\"span_resource_attribute\", use the attribute key (e.g. \"http.method\").'
        ),
    type: SpanPropertyTypeEnumApi.describe(
        '\"span\" filters built-in span fields. \"span_attribute\" filters span-level attributes. \"span_resource_attribute\" filters resource-level attributes.\n\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
    ),
    operator: _SpanPropertyFilterOperatorEnumApi.describe(
        'Comparison operator.\n\n\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
    ),
    value: zod
        .unknown()
        .optional()
        .describe(
            'Value to compare against. String, number, or array of strings. Omit for is_set\/is_not_set operators.'
        ),
})

export type _SpanPropertyFilterApi = zod.input<typeof _SpanPropertyFilterApi>
export type _SpanPropertyFilterApiOutput = zod.output<typeof _SpanPropertyFilterApi>

export const _tracingAggregationQueryBodyApiFilterGroupDefault = []
export const _tracingAggregationQueryBodyApiLimitMax = 5000

export const _tracingAggregationQueryBodyApiOffsetMin = 0

export const _TracingAggregationQueryBodyApi = zod.object({
    dateRange: _TracingDateRangeApi.optional().describe('Date range for the primary window. Defaults to last hour.'),
    compareFilter: _CompareFilterApi
        .optional()
        .describe('Optional comparison-window configuration. When omitted, only the primary window is returned.'),
    serviceNames: zod.array(zod.string()).optional().describe('Filter by service names.'),
    filterGroup: zod
        .array(_SpanPropertyFilterApi)
        .default(_tracingAggregationQueryBodyApiFilterGroupDefault)
        .describe('Property filters applied to spans in both windows.'),
    limit: zod
        .number()
        .min(1)
        .max(_tracingAggregationQueryBodyApiLimitMax)
        .optional()
        .describe(
            'Max rows to return, ordered by total_duration_nano DESC. Defaults to 100; hard max 5000. Keep this small to bound the response size — a high value on high-cardinality span names (e.g. untemplated URL paths) returns a very large payload. Prefer narrowing with `serviceNames`\/`filterGroup` over raising the limit.'
        ),
    offset: zod
        .number()
        .min(_tracingAggregationQueryBodyApiOffsetMin)
        .optional()
        .describe(
            'Row offset for pagination. Combine with `limit` and the `next_offset` returned in the response to page through results beyond the first page.'
        ),
})

export type _TracingAggregationQueryBodyApi = zod.input<typeof _TracingAggregationQueryBodyApi>
export type _TracingAggregationQueryBodyApiOutput = zod.output<typeof _TracingAggregationQueryBodyApi>

export const _TracingAggregationRequestApi = zod.object({
    query: _TracingAggregationQueryBodyApi.describe('The span aggregation query to execute.'),
})

export type _TracingAggregationRequestApi = zod.input<typeof _TracingAggregationRequestApi>
export type _TracingAggregationRequestApiOutput = zod.output<typeof _TracingAggregationRequestApi>

export const _AggregatedSpanRowApi = zod.object({
    service_name: zod.string().describe('Service that emitted the spans in this group.'),
    name: zod.string().describe('Span name (operation) for this group.'),
    count: zod.number().describe('Number of spans matched in this group.'),
    total_duration_nano: zod.number().describe('Sum of span durations in nanoseconds.'),
    avg_duration_nano: zod.number().describe('Average span duration in nanoseconds.'),
    p50_duration_nano: zod.number().describe('Median span duration in nanoseconds.'),
    p95_duration_nano: zod.number().describe('95th percentile span duration in nanoseconds.'),
    p99_duration_nano: zod.number().describe('99th percentile span duration in nanoseconds.'),
    p999_duration_nano: zod.number().describe('99.9th percentile span duration in nanoseconds.'),
    error_count: zod.number().describe('Spans with OTel status code Error (status_code = 2).'),
})

export type _AggregatedSpanRowApi = zod.input<typeof _AggregatedSpanRowApi>
export type _AggregatedSpanRowApiOutput = zod.output<typeof _AggregatedSpanRowApi>

export const _TracingAggregationResponseApi = zod.object({
    results: zod
        .array(_AggregatedSpanRowApi)
        .describe('One row per (service_name, name) group, ordered by total_duration_nano descending.'),
    compare: zod
        .array(_AggregatedSpanRowApi)
        .nullable()
        .describe('Rows for the comparison window when compareFilter.compare is true, else null.'),
    has_more: zod
        .boolean()
        .describe('True when more rows exist beyond this page — page further with `next_offset`, or narrow the query.'),
    next_offset: zod
        .number()
        .nullable()
        .describe('Offset to request the next page, or null when this is the last page.'),
})

export type _TracingAggregationResponseApi = zod.input<typeof _TracingAggregationResponseApi>
export type _TracingAggregationResponseApiOutput = zod.output<typeof _TracingAggregationResponseApi>

export const _TracingAttributeBreakdownQueryBodyOrderByEnumApi = zod
    .enum(['count', 'error_count'])
    .describe('\* `count` - count\n\* `error_count` - error_count')

export type _TracingAttributeBreakdownQueryBodyOrderByEnumApi = zod.input<
    typeof _TracingAttributeBreakdownQueryBodyOrderByEnumApi
>
export type _TracingAttributeBreakdownQueryBodyOrderByEnumApiOutput = zod.output<
    typeof _TracingAttributeBreakdownQueryBodyOrderByEnumApi
>

export const _tracingAttributeBreakdownQueryBodyApiExcludeBreakdownFilterDefault = false
export const _tracingAttributeBreakdownQueryBodyApiFilterGroupDefault = []

export const _TracingAttributeBreakdownQueryBodyApi = zod.object({
    breakdownKey: zod
        .string()
        .describe(
            'Attribute key to group by (e.g. \"server.address\", \"http.response.status_code\"). Discover keys with apm-attributes-list. For the \"span\" breakdown type, must be one of the allowlisted top-level columns: \"service_name\", \"status_code\".'
        ),
    breakdownType: SpanPropertyTypeEnumApi.describe(
        'Where the key lives: \"span\" for allowlisted top-level span columns, \"span_attribute\" for span-level attributes, \"span_resource_attribute\" for resource-level attributes.\n\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute'
    ),
    excludeBreakdownFilter: zod
        .boolean()
        .default(_tracingAttributeBreakdownQueryBodyApiExcludeBreakdownFilterDefault)
        .describe(
            "Drop filters targeting the breakdown key itself (including serviceNames for a service_name breakdown), so a facet's value list stays complete while one of its values is selected."
        ),
    facetSearch: zod
        .string()
        .optional()
        .describe(
            "Type-ahead filter over the breakdown field's own values (case-insensitive substring match). An empty string means no filter. Lets a facet's value search reach past the row limit."
        ),
    orderBy: _TracingAttributeBreakdownQueryBodyOrderByEnumApi
        .optional()
        .describe(
            'Order rows by span count or error count, descending. Defaults to count.\n\n\* `count` - count\n\* `error_count` - error_count'
        ),
    dateRange: _TracingDateRangeApi.optional().describe('Date range for the primary window. Defaults to last hour.'),
    compareFilter: _CompareFilterApi
        .optional()
        .describe('Optional comparison-window configuration. When omitted, only the primary window is returned.'),
    serviceNames: zod.array(zod.string()).optional().describe('Filter by service names.'),
    filterGroup: zod
        .array(_SpanPropertyFilterApi)
        .default(_tracingAttributeBreakdownQueryBodyApiFilterGroupDefault)
        .describe('Property filters scoping the spans the breakdown runs over (e.g. only error spans).'),
})

export type _TracingAttributeBreakdownQueryBodyApi = zod.input<typeof _TracingAttributeBreakdownQueryBodyApi>
export type _TracingAttributeBreakdownQueryBodyApiOutput = zod.output<typeof _TracingAttributeBreakdownQueryBodyApi>

export const _TracingAttributeBreakdownRequestApi = zod.object({
    query: _TracingAttributeBreakdownQueryBodyApi.describe('The attribute breakdown query to execute.'),
})

export type _TracingAttributeBreakdownRequestApi = zod.input<typeof _TracingAttributeBreakdownRequestApi>
export type _TracingAttributeBreakdownRequestApiOutput = zod.output<typeof _TracingAttributeBreakdownRequestApi>

export const _TracingAttributeBreakdownRowApi = zod.object({
    value: zod.string().describe("The attribute's value for this group. Spans without the attribute group under ''."),
    count: zod.number().describe('Number of matching spans with this value.'),
    error_count: zod.number().describe('Number of matching error spans (status_code = 2).'),
    p50_duration_nano: zod.number().describe('Median span duration in nanoseconds.'),
    p95_duration_nano: zod.number().describe('95th percentile span duration in nanoseconds.'),
})

export type _TracingAttributeBreakdownRowApi = zod.input<typeof _TracingAttributeBreakdownRowApi>
export type _TracingAttributeBreakdownRowApiOutput = zod.output<typeof _TracingAttributeBreakdownRowApi>

export const _TracingAttributeBreakdownResponseApi = zod.object({
    results: zod
        .array(_TracingAttributeBreakdownRowApi)
        .describe('One row per distinct attribute value, ordered by the requested column descending.'),
    compare: zod
        .array(_TracingAttributeBreakdownRowApi)
        .nullable()
        .describe('Rows for the comparison window when compareFilter.compare is true, else null.'),
})

export type _TracingAttributeBreakdownResponseApi = zod.input<typeof _TracingAttributeBreakdownResponseApi>
export type _TracingAttributeBreakdownResponseApiOutput = zod.output<typeof _TracingAttributeBreakdownResponseApi>

export const MatchedOnEnumApi = zod.enum(['key', 'value']).describe('\* `key` - key\n\* `value` - value')

export type MatchedOnEnumApi = zod.input<typeof MatchedOnEnumApi>
export type MatchedOnEnumApiOutput = zod.output<typeof MatchedOnEnumApi>

export const _TracingAttributeEntryApi = zod.object({
    name: zod.string().describe('Attribute key name.'),
    propertyFilterType: zod
        .string()
        .describe(
            'Property filter type: \"span_attribute\" or \"span_resource_attribute\". Use this as the `type` field when filtering.'
        ),
    matchedOn: MatchedOnEnumApi.describe(
        'How the search query matched this row: \"key\" if the attribute key matched, \"value\" if a value matched.\n\n\* `key` - key\n\* `value` - value'
    ),
    matchedValue: zod.string().nullish().describe('Sample matching value — only set when matchedOn is \"value\".'),
})

export type _TracingAttributeEntryApi = zod.input<typeof _TracingAttributeEntryApi>
export type _TracingAttributeEntryApiOutput = zod.output<typeof _TracingAttributeEntryApi>

export const _TracingAttributesResponseApi = zod.object({
    results: zod.array(_TracingAttributeEntryApi).describe('Available attribute keys matching the filters.'),
    count: zod.number().describe('Total attribute keys matched (lower bound when searching values).'),
})

export type _TracingAttributesResponseApi = zod.input<typeof _TracingAttributesResponseApi>
export type _TracingAttributesResponseApiOutput = zod.output<typeof _TracingAttributesResponseApi>

export const _tracingCountBodyApiFilterGroupDefault = []

export const _TracingCountBodyApi = zod.object({
    dateRange: _TracingDateRangeApi.optional().describe('Date range for the count. Defaults to last hour.'),
    serviceNames: zod.array(zod.string()).optional().describe('Filter by service names.'),
    statusCodes: zod
        .array(zod.number())
        .optional()
        .describe(
            'Filter by OTel span status codes (0 Unset, 1 OK, 2 Error) — not HTTP status codes. Use [2] to select error spans.'
        ),
    filterGroup: zod
        .array(_SpanPropertyFilterApi)
        .default(_tracingCountBodyApiFilterGroupDefault)
        .describe('Property filters for the count.'),
})

export type _TracingCountBodyApi = zod.input<typeof _TracingCountBodyApi>
export type _TracingCountBodyApiOutput = zod.output<typeof _TracingCountBodyApi>

export const _TracingCountRequestApi = zod.object({
    query: _TracingCountBodyApi.describe('The span count query to execute.'),
})

export type _TracingCountRequestApi = zod.input<typeof _TracingCountRequestApi>
export type _TracingCountRequestApiOutput = zod.output<typeof _TracingCountRequestApi>

export const _TracingCountResponseApi = zod.object({
    count: zod.number().describe('Number of spans matching the filters.'),
    traceCount: zod
        .number()
        .describe(
            'Number of distinct traces whose root span matches the filters — the trace count shown in the Traces view.'
        ),
})

export type _TracingCountResponseApi = zod.input<typeof _TracingCountResponseApi>
export type _TracingCountResponseApiOutput = zod.output<typeof _TracingCountResponseApi>

export const _tracingDurationHistogramQueryBodyApiFilterGroupDefault = []
export const _tracingDurationHistogramQueryBodyApiRootSpansDefault = true

export const _TracingDurationHistogramQueryBodyApi = zod.object({
    dateRange: _TracingDateRangeApi.optional().describe('Date range for the query. Defaults to last hour.'),
    serviceNames: zod.array(zod.string()).optional().describe('Filter by service names.'),
    statusCodes: zod
        .array(zod.number())
        .optional()
        .describe(
            'Filter by OTel span status codes (0 Unset, 1 OK, 2 Error) — not HTTP status codes. Use [2] to select error spans.'
        ),
    filterGroup: zod
        .array(_SpanPropertyFilterApi)
        .default(_tracingDurationHistogramQueryBodyApiFilterGroupDefault)
        .describe('Property filters for the query.'),
    rootSpans: zod
        .boolean()
        .default(_tracingDurationHistogramQueryBodyApiRootSpansDefault)
        .describe(
            'When true (default), bucket root-span durations only — a distribution of traces. When false, bucket every matching span — used with a span name filter for operation-scoped distributions.'
        ),
})

export type _TracingDurationHistogramQueryBodyApi = zod.input<typeof _TracingDurationHistogramQueryBodyApi>
export type _TracingDurationHistogramQueryBodyApiOutput = zod.output<typeof _TracingDurationHistogramQueryBodyApi>

export const _TracingDurationHistogramRequestApi = zod.object({
    query: _TracingDurationHistogramQueryBodyApi.describe('The duration-histogram query to execute.'),
})

export type _TracingDurationHistogramRequestApi = zod.input<typeof _TracingDurationHistogramRequestApi>
export type _TracingDurationHistogramRequestApiOutput = zod.output<typeof _TracingDurationHistogramRequestApi>

export const _HasSpansResponseApi = zod.object({
    hasSpans: zod
        .boolean()
        .describe('Whether the team has ingested any tracing spans yet. Used to gate the onboarding empty state.'),
})

export type _HasSpansResponseApi = zod.input<typeof _HasSpansResponseApi>
export type _HasSpansResponseApiOutput = zod.output<typeof _HasSpansResponseApi>

export const _TracingLatencyHeatmapRequestApi = zod.object({
    query: _TracingDurationHistogramQueryBodyApi.describe('The latency-heatmap query to execute.'),
})

export type _TracingLatencyHeatmapRequestApi = zod.input<typeof _TracingLatencyHeatmapRequestApi>
export type _TracingLatencyHeatmapRequestApiOutput = zod.output<typeof _TracingLatencyHeatmapRequestApi>

export const _TracingLatencyHeatmapCellApi = zod.object({
    time: zod.string().describe('ISO 8601 UTC start of the time bucket.'),
    bucket_ns: zod
        .number()
        .describe(
            'Lower edge of the 1-2-5 series duration bucket in nanoseconds (1ms, 2ms, 5ms, 10ms, ...). 0 on the sentinel row that enumerates a time bucket with no matching spans.'
        ),
    count: zod
        .number()
        .describe(
            'Traces in this cell, bucketed by root-span duration (the default, rootSpans=true). When rootSpans is false, every matching span is counted instead. 0 only on sentinel rows.'
        ),
})

export type _TracingLatencyHeatmapCellApi = zod.input<typeof _TracingLatencyHeatmapCellApi>
export type _TracingLatencyHeatmapCellApiOutput = zod.output<typeof _TracingLatencyHeatmapCellApi>

export const _TracingLatencyHeatmapResponseApi = zod.object({
    results: zod
        .array(_TracingLatencyHeatmapCellApi)
        .describe(
            'Sparse heatmap cells ordered by time then duration bucket. Every time bucket in the window appears in at least one row, so the full x axis can be derived from the response.'
        ),
})

export type _TracingLatencyHeatmapResponseApi = zod.input<typeof _TracingLatencyHeatmapResponseApi>
export type _TracingLatencyHeatmapResponseApiOutput = zod.output<typeof _TracingLatencyHeatmapResponseApi>

export const _TracingQueryBodyOrderByEnumApi = zod
    .enum(['timestamp', 'duration'])
    .describe('\* `timestamp` - timestamp\n\* `duration` - duration')

export type _TracingQueryBodyOrderByEnumApi = zod.input<typeof _TracingQueryBodyOrderByEnumApi>
export type _TracingQueryBodyOrderByEnumApiOutput = zod.output<typeof _TracingQueryBodyOrderByEnumApi>

export const OrderDirectionEnumApi = zod.enum(['ASC', 'DESC']).describe('\* `ASC` - ASC\n\* `DESC` - DESC')

export type OrderDirectionEnumApi = zod.input<typeof OrderDirectionEnumApi>
export type OrderDirectionEnumApiOutput = zod.output<typeof OrderDirectionEnumApi>

export const _tracingQueryBodyApiFilterGroupDefault = []
export const _tracingQueryBodyApiLimitDefault = 100
export const _tracingQueryBodyApiOffsetMin = 0

export const _tracingQueryBodyApiRootSpansDefault = true
export const _tracingQueryBodyApiFlatSpansDefault = false
export const _tracingQueryBodyApiExcludeAttributesDefault = false

export const _TracingQueryBodyApi = zod.object({
    dateRange: _TracingDateRangeApi.optional().describe('Date range for the query. Defaults to last hour.'),
    serviceNames: zod.array(zod.string()).optional().describe('Filter by service names.'),
    statusCodes: zod
        .array(zod.number())
        .optional()
        .describe(
            'Filter by OTel span status codes (0 Unset, 1 OK, 2 Error) — not HTTP status codes. Use [2] to select error spans.'
        ),
    orderBy: _TracingQueryBodyOrderByEnumApi
        .optional()
        .describe(
            "Column to order by. Defaults to timestamp. Ordering by timestamp paginates via the keyset cursor ('after'); ordering by duration paginates via 'offset'.\n\n\* `timestamp` - timestamp\n\* `duration` - duration"
        ),
    orderDirection: OrderDirectionEnumApi.optional().describe(
        'Order direction. Defaults to DESC (e.g. timestamp+DESC = newest first, duration+DESC = slowest first).\n\n\* `ASC` - ASC\n\* `DESC` - DESC'
    ),
    filterGroup: zod
        .array(_SpanPropertyFilterApi)
        .default(_tracingQueryBodyApiFilterGroupDefault)
        .describe('Property filters for the query.'),
    traceId: zod.string().optional().describe('Filter to a specific trace ID (hex string).'),
    limit: zod.number().default(_tracingQueryBodyApiLimitDefault).describe('Max results (1-1000). Defaults to 100.'),
    after: zod.string().optional().describe('Keyset pagination cursor from a previous timestamp-ordered response.'),
    offset: zod
        .number()
        .min(_tracingQueryBodyApiOffsetMin)
        .optional()
        .describe('Pagination offset, used when ordering by a column (e.g. duration). Defaults to 0.'),
    rootSpans: zod
        .boolean()
        .default(_tracingQueryBodyApiRootSpansDefault)
        .describe('Filter to root spans only. Defaults to true.'),
    flatSpans: zod
        .boolean()
        .default(_tracingQueryBodyApiFlatSpansDefault)
        .describe(
            'Return the matching spans themselves, one row per span (root and child), instead of collapsing to traces. Use this to search by a child-span attribute (e.g. code.filepath) without the whole-trace grouping. Distinct from rootSpans. Defaults to false.'
        ),
    prefetchSpans: zod.number().optional().describe('Number of child spans to prefetch per trace (1-100).'),
    excludeAttributes: zod
        .boolean()
        .default(_tracingQueryBodyApiExcludeAttributesDefault)
        .describe(
            'Omit the per-span attributes and resource attributes maps from results to keep payloads compact. Defaults to false.'
        ),
})

export type _TracingQueryBodyApi = zod.input<typeof _TracingQueryBodyApi>
export type _TracingQueryBodyApiOutput = zod.output<typeof _TracingQueryBodyApi>

export const _TracingQueryRequestApi = zod.object({
    query: _TracingQueryBodyApi.describe('The tracing spans query to execute.'),
})

export type _TracingQueryRequestApi = zod.input<typeof _TracingQueryRequestApi>
export type _TracingQueryRequestApiOutput = zod.output<typeof _TracingQueryRequestApi>

export const _tracingSparklineQueryBodyApiFilterGroupDefault = []
export const _tracingSparklineQueryBodyApiRootSpansDefault = false

export const _TracingSparklineQueryBodyApi = zod.object({
    dateRange: _TracingDateRangeApi.optional().describe('Date range for the query. Defaults to last hour.'),
    serviceNames: zod.array(zod.string()).optional().describe('Filter by service names.'),
    statusCodes: zod
        .array(zod.number())
        .optional()
        .describe(
            'Filter by OTel span status codes (0 Unset, 1 OK, 2 Error) — not HTTP status codes. Use [2] to select error spans.'
        ),
    filterGroup: zod
        .array(_SpanPropertyFilterApi)
        .default(_tracingSparklineQueryBodyApiFilterGroupDefault)
        .describe('Property filters for the query.'),
    rootSpans: zod
        .boolean()
        .default(_tracingSparklineQueryBodyApiRootSpansDefault)
        .describe(
            "When true, count only root spans (one per trace) so the bars reflect the Traces view. When false (default), count every matching span — the Spans view's volume."
        ),
})

export type _TracingSparklineQueryBodyApi = zod.input<typeof _TracingSparklineQueryBodyApi>
export type _TracingSparklineQueryBodyApiOutput = zod.output<typeof _TracingSparklineQueryBodyApi>

export const _TracingSparklineRequestApi = zod.object({
    query: _TracingSparklineQueryBodyApi.describe('The sparkline query to execute.'),
})

export type _TracingSparklineRequestApi = zod.input<typeof _TracingSparklineRequestApi>
export type _TracingSparklineRequestApiOutput = zod.output<typeof _TracingSparklineRequestApi>

export const _SymbolStatsSymbolApi = zod.object({
    name: zod
        .string()
        .nullish()
        .describe('Opaque identifier (e.g. the function name) echoed back on the matching result row.'),
    startLine: zod.number().min(1).describe("First line of the symbol's range, inclusive."),
    endLine: zod.number().min(1).describe("Last line of the symbol's range, inclusive."),
})

export type _SymbolStatsSymbolApi = zod.input<typeof _SymbolStatsSymbolApi>
export type _SymbolStatsSymbolApiOutput = zod.output<typeof _SymbolStatsSymbolApi>

export const _SymbolStatsQueryBodyApi = zod.object({
    filePath: zod
        .string()
        .describe(
            "Repo-relative path of the source file to aggregate (e.g. 'src\/flags\/flag_matching.rs'). Matched as a path suffix against the recorded OTel code.file.path \/ code.filepath, so a recorded path carrying an extra crate\/workspace prefix still matches. Separators are normalized."
        ),
    dateRange: _TracingDateRangeApi
        .optional()
        .describe(
            'Current period to aggregate over; the prior equal-length window is the comparison. Defaults to last 24h.'
        ),
    symbols: zod
        .array(_SymbolStatsSymbolApi)
        .optional()
        .describe(
            'Optional symbol (function) line ranges, supplied by the client from its own AST\/LSP. When given, each span is attributed to the smallest enclosing range (one row per symbol). When omitted (or an empty list), spans are aggregated per source line (one row per line); pass a single whole-file range for a file-level total.'
        ),
})

export type _SymbolStatsQueryBodyApi = zod.input<typeof _SymbolStatsQueryBodyApi>
export type _SymbolStatsQueryBodyApiOutput = zod.output<typeof _SymbolStatsQueryBodyApi>

export const _SymbolStatsRequestApi = zod.object({
    query: _SymbolStatsQueryBodyApi.describe('The symbol-stats per-symbol aggregation query to execute.'),
})

export type _SymbolStatsRequestApi = zod.input<typeof _SymbolStatsRequestApi>
export type _SymbolStatsRequestApiOutput = zod.output<typeof _SymbolStatsRequestApi>

export const _SymbolStatsPeriodApi = zod.object({
    count: zod.number().describe('Number of spans attributed to this symbol in the period.'),
    error_count: zod.number().describe('Spans whose OTel status is Error (status_code = 2).'),
    sum_duration_nano: zod
        .number()
        .describe('Total wall-clock span duration in the period, in nanoseconds (additive across spans).'),
    p50_duration_nano: zod.number().describe('Median wall-clock span duration, in nanoseconds.'),
    p95_duration_nano: zod.number().describe('95th-percentile wall-clock span duration, in nanoseconds.'),
    p99_duration_nano: zod.number().describe('99th-percentile wall-clock span duration, in nanoseconds.'),
    busy_count: zod
        .number()
        .describe('Spans in the period carrying an active\/busy time attribute. 0 means busy_\* are not meaningful.'),
    p50_busy_nano: zod.number().describe('Median active (busy) time, in nanoseconds. Excludes awaiting children.'),
    p95_busy_nano: zod.number().describe('95th-percentile active (busy) time, in nanoseconds.'),
    p99_busy_nano: zod.number().describe('99th-percentile active (busy) time, in nanoseconds.'),
})

export type _SymbolStatsPeriodApi = zod.input<typeof _SymbolStatsPeriodApi>
export type _SymbolStatsPeriodApiOutput = zod.output<typeof _SymbolStatsPeriodApi>

export const _SymbolStatsRowApi = zod.object({
    count: zod.number().describe('Number of spans attributed to this symbol in the period.'),
    error_count: zod.number().describe('Spans whose OTel status is Error (status_code = 2).'),
    sum_duration_nano: zod
        .number()
        .describe('Total wall-clock span duration in the period, in nanoseconds (additive across spans).'),
    p50_duration_nano: zod.number().describe('Median wall-clock span duration, in nanoseconds.'),
    p95_duration_nano: zod.number().describe('95th-percentile wall-clock span duration, in nanoseconds.'),
    p99_duration_nano: zod.number().describe('99th-percentile wall-clock span duration, in nanoseconds.'),
    busy_count: zod
        .number()
        .describe('Spans in the period carrying an active\/busy time attribute. 0 means busy_\* are not meaningful.'),
    p50_busy_nano: zod.number().describe('Median active (busy) time, in nanoseconds. Excludes awaiting children.'),
    p95_busy_nano: zod.number().describe('95th-percentile active (busy) time, in nanoseconds.'),
    p99_busy_nano: zod.number().describe('99th-percentile active (busy) time, in nanoseconds.'),
    line: zod.number().describe("Bucket anchor: the source line (line mode) or the symbol's startLine (symbol mode)."),
    name: zod.string().nullish().describe('Echoed name from the requested symbol (symbol mode only).'),
    end_line: zod.number().nullish().describe("endLine of the matched symbol's range (symbol mode only)."),
    previous: _SymbolStatsPeriodApi.describe('The same metrics over the immediately-preceding equal-length period.'),
    count_pct_change: zod
        .number()
        .nullable()
        .describe(
            'Percentage change in count vs the previous period (180 = +180%). Null when there is no baseline (previous count 0). Use `previous.count` — not a null here — to detect a new symbol.'
        ),
    p95_duration_pct_change: zod
        .number()
        .nullable()
        .describe(
            "Percentage change in p95 duration vs the previous period (180 = +180%). Null when the previous p95 is 0 (no comparable baseline), which can occur even when previous.count > 0 — do not read null as 'new symbol'."
        ),
})

export type _SymbolStatsRowApi = zod.input<typeof _SymbolStatsRowApi>
export type _SymbolStatsRowApiOutput = zod.output<typeof _SymbolStatsRowApi>

export const GranularityEnumApi = zod.enum(['line', 'symbol']).describe('\* `line` - line\n\* `symbol` - symbol')

export type GranularityEnumApi = zod.input<typeof GranularityEnumApi>
export type GranularityEnumApiOutput = zod.output<typeof GranularityEnumApi>

export const _SymbolStatsResponseApi = zod.object({
    results: zod.array(_SymbolStatsRowApi).describe('One row per bucket, ordered by line ascending.'),
    granularity: GranularityEnumApi.describe(
        "Bucketing applied: 'line' when no symbols were supplied, 'symbol' otherwise.\n\n\* `line` - line\n\* `symbol` - symbol"
    ),
})

export type _SymbolStatsResponseApi = zod.input<typeof _SymbolStatsResponseApi>
export type _SymbolStatsResponseApiOutput = zod.output<typeof _SymbolStatsResponseApi>

export const _tracingTraceRequestApiExcludeAttributesDefault = false
export const _tracingTraceRequestApiOffsetMin = 0

export const _TracingTraceRequestApi = zod.object({
    dateRange: _TracingDateRangeApi.optional().describe('Date range for the query. Defaults to last 24 hours.'),
    excludeAttributes: zod
        .boolean()
        .default(_tracingTraceRequestApiExcludeAttributesDefault)
        .describe(
            'Omit the per-span attributes and resource attributes maps from results to keep payloads compact. Defaults to false.'
        ),
    offset: zod
        .number()
        .min(_tracingTraceRequestApiOffsetMin)
        .optional()
        .describe(
            "Pagination offset into the trace's spans (ordered by start time ascending). Each page returns up to 2000 spans; pass the response's `nextOffset` to load the next page. Defaults to 0."
        ),
})

export type _TracingTraceRequestApi = zod.input<typeof _TracingTraceRequestApi>
export type _TracingTraceRequestApiOutput = zod.output<typeof _TracingTraceRequestApi>

export const _tracingTreeQueryBodyApiFilterGroupDefault = []

export const _TracingTreeQueryBodyApi = zod.object({
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
    dateRange: _TracingDateRangeApi.optional().describe('Date range for the primary window. Defaults to last hour.'),
    compareFilter: _CompareFilterApi
        .optional()
        .describe('Optional comparison-window configuration. When omitted, only the primary window is returned.'),
    serviceNames: zod.array(zod.string()).optional().describe('Filter by service names.'),
    filterGroup: zod
        .array(_SpanPropertyFilterApi)
        .default(_tracingTreeQueryBodyApiFilterGroupDefault)
        .describe('Additional property filters applied to spans in both windows.'),
})

export type _TracingTreeQueryBodyApi = zod.input<typeof _TracingTreeQueryBodyApi>
export type _TracingTreeQueryBodyApiOutput = zod.output<typeof _TracingTreeQueryBodyApi>

export const _TracingTreeRequestApi = zod.object({
    query: _TracingTreeQueryBodyApi.describe('The span call-tree aggregation query to execute.'),
})

export type _TracingTreeRequestApi = zod.input<typeof _TracingTreeRequestApi>
export type _TracingTreeRequestApiOutput = zod.output<typeof _TracingTreeRequestApi>

export const RoleAtOrganizationEnumApi = zod
    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
    .describe(
        '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
    )

export type RoleAtOrganizationEnumApi = zod.input<typeof RoleAtOrganizationEnumApi>
export type RoleAtOrganizationEnumApiOutput = zod.output<typeof RoleAtOrganizationEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

export const userBasicApiDistinctIdMax = 200

export const userBasicApiFirstNameMax = 150

export const userBasicApiLastNameMax = 150

export const userBasicApiEmailMax = 254

export const UserBasicApi = zod.object({
    id: zod.number(),
    uuid: zod.uuid(),
    distinct_id: zod.string().max(userBasicApiDistinctIdMax).nullish(),
    first_name: zod.string().max(userBasicApiFirstNameMax).optional(),
    last_name: zod.string().max(userBasicApiLastNameMax).optional(),
    email: zod.email().max(userBasicApiEmailMax),
    is_email_verified: zod.boolean().nullish(),
    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
    role_at_organization: zod.union([RoleAtOrganizationEnumApi, BlankEnumApi, zod.null()]).optional(),
})

export type UserBasicApi = zod.input<typeof UserBasicApi>
export type UserBasicApiOutput = zod.output<typeof UserBasicApi>

export const tracingViewApiNameMax = 400

export const TracingViewApi = zod.object({
    id: zod.uuid(),
    short_id: zod.string(),
    name: zod.string().max(tracingViewApiNameMax).describe('Human-readable name shown in the saved views list.'),
    filters: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Saved tracing filters — a subset of the frontend TracingFilters shape. May contain dateRange, serviceNames, filterGroup, orderBy, orderDirection, and viewMode.'
        ),
    pinned: zod.boolean().optional().describe('Whether the view is pinned for quick access.'),
    created_at: zod.iso.datetime({ offset: true }),
    created_by: zod.union([UserBasicApi, zod.null()]).describe('User who created the view.'),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
})

export type TracingViewApi = zod.input<typeof TracingViewApi>
export type TracingViewApiOutput = zod.output<typeof TracingViewApi>

export const PaginatedTracingViewListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(TracingViewApi),
})

export type PaginatedTracingViewListApi = zod.input<typeof PaginatedTracingViewListApi>
export type PaginatedTracingViewListApiOutput = zod.output<typeof PaginatedTracingViewListApi>

export const patchedTracingViewApiNameMax = 400

export const PatchedTracingViewApi = zod.object({
    id: zod.uuid().optional(),
    short_id: zod.string().optional(),
    name: zod
        .string()
        .max(patchedTracingViewApiNameMax)
        .optional()
        .describe('Human-readable name shown in the saved views list.'),
    filters: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Saved tracing filters — a subset of the frontend TracingFilters shape. May contain dateRange, serviceNames, filterGroup, orderBy, orderDirection, and viewMode.'
        ),
    pinned: zod.boolean().optional().describe('Whether the view is pinned for quick access.'),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    created_by: zod.union([UserBasicApi, zod.null()]).optional().describe('User who created the view.'),
    updated_at: zod.iso.datetime({ offset: true }).nullish(),
})

export type PatchedTracingViewApi = zod.input<typeof PatchedTracingViewApi>
export type PatchedTracingViewApiOutput = zod.output<typeof PatchedTracingViewApi>
