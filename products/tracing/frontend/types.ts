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

// The trace drawer's inspector tabs. Query, Metrics and Errors are conditional, so the active tab
// can point at a tab the drawer is not currently rendering.
export type SpanInspectorTab = 'attributes' | 'query' | 'logs' | 'metrics' | 'errors' | 'raw'
