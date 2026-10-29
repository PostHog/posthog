import type { _SpanEventApi } from './generated/api.schemas'

export interface Span {
    uuid: string
    trace_id: string
    span_id: string
    parent_span_id: string
    name: string
    kind: number
    service_name: string
    status_code: number
    timestamp: string
    end_time: string
    duration_nano: number
    is_root_span: boolean
    matched_filter: boolean
    // OTel span attributes the user set, as a key-value map.
    attributes: Record<string, string>
    // OTel resource attributes (who/what emitted the span: service.version, host, k8s, ...).
    resource_attributes: Record<string, string>
    // OTel span events, earliest first. Only the single-trace endpoint returns them.
    events?: _SpanEventApi[]
    trace_start?: string
    trace_duration?: number
    // Set on a span shown in place of a root span that was not found.
    root_missing?: boolean
}

export const SPAN_KIND_LABELS: Record<number, string> = {
    0: 'Unspecified',
    1: 'Internal',
    2: 'Server',
    3: 'Client',
    4: 'Producer',
    5: 'Consumer',
}

// In the Otel standard, "unset" is treated as "OK".
// It's stored separately in the backend but should be treated identically to the user
export const STATUS_CODE_LABELS: Record<number, { label: string; type: 'success' | 'warning' | 'danger' | 'default' }> =
    {
        0: { label: 'OK', type: 'success' },
        1: { label: 'OK', type: 'success' },
        2: { label: 'Error', type: 'danger' },
    }

// The trace drawer's inspector tabs. Query, Errors, Operations and Metrics are conditional, so the
// active tab can point at a tab the drawer is not currently rendering. Pinned: analytics events send
// these values as the `tab` property, so renaming one breaks the insights built on it.
export type SpanInspectorTab = 'attributes' | 'query' | 'logs' | 'errors' | 'operations' | 'metrics' | 'raw'

/**
 * The views the left pane of a trace view can show. Pinned: the values are persisted, and analytics events send them as
 * the `view` property.
 */
export const TRACE_VIEW_MODES = ['waterfall', 'calltree'] as const
export type TraceViewMode = (typeof TRACE_VIEW_MODES)[number]
