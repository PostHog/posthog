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
}

export const SPAN_KIND_LABELS: Record<number, string> = {
    0: 'Unspecified',
    1: 'Internal',
    2: 'Server',
    3: 'Client',
    4: 'Producer',
    5: 'Consumer',
}

export const STATUS_CODE_LABELS: Record<number, { label: string; type: 'success' | 'warning' | 'danger' | 'default' }> =
    {
        0: { label: 'Unset', type: 'default' },
        1: { label: 'OK', type: 'success' },
        2: { label: 'Error', type: 'danger' },
    }
