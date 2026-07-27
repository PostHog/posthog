// Correlate logs to a trace/span (JON-30). OTel logs carry native `trace_id`/`span_id` columns
// (products/logs/backend/schema.sql), so scoping the embedded LogsViewer to a span or the whole
// trace is just a `trace_id`/`span_id` equality filter — no tracing-side backend needed.

import { urls } from 'scenes/urls'

import type { DateRange } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, type LogPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'
import type { UniversalFiltersGroup } from '~/types'

export type TraceLogScope = 'span' | 'trace'

export interface TraceSpanIds {
    traceId: string
    spanId: string
}

function scopeFilter(scope: TraceLogScope, { traceId, spanId }: TraceSpanIds): LogPropertyFilter {
    // trace_id/span_id are native log columns; the logs query runner accepts hex and converts to
    // the stored base64 form, so we pass the hex ids the trace UI already has.
    return {
        key: scope === 'span' ? 'span_id' : 'trace_id',
        type: PropertyFilterType.Log,
        operator: PropertyOperator.Exact,
        value: [scope === 'span' ? spanId : traceId],
    } as LogPropertyFilter
}

/**
 * Read-only `pinnedFilters` for the embedded LogsViewer — locks it to this span's (or trace's)
 * logs. Single-level group shape, matching how PersonLogsTab pins its scope.
 */
export function buildLogScopeFilter(scope: TraceLogScope, ids: TraceSpanIds): UniversalFiltersGroup {
    return {
        type: FilterLogicalOperator.And,
        values: [scopeFilter(scope, ids)],
    }
}

/**
 * Deep link into the full Logs product, pre-scoped to this span/trace and time window. Two-level
 * group + JSON-encoded params, matching the format the logs scene's urlToAction decodes (see
 * ItemLog's logs link).
 */
export function logsDeepLinkUrl(scope: TraceLogScope, ids: TraceSpanIds, dateRange: DateRange): string {
    // The logs scene decodes an outer group of inner groups, so wrap the pinned group one level.
    const filterGroup = {
        type: FilterLogicalOperator.And,
        values: [buildLogScopeFilter(scope, ids)],
    }
    const params = new URLSearchParams({
        filterGroup: JSON.stringify(filterGroup),
        dateRange: JSON.stringify(dateRange),
    })
    return `${urls.logs()}?${params.toString()}`
}
