import type { Span } from '../types'

export function makeSpan(overrides: Partial<Span> = {}): Span {
    return {
        uuid: 'uuid',
        trace_id: 'trace-1',
        span_id: 'span-1',
        parent_span_id: '',
        name: 'GET /checkout',
        kind: 2,
        service_name: 'checkout-api',
        status_code: 0,
        timestamp: '2026-09-03T10:00:00Z',
        end_time: '2026-09-03T10:00:01Z',
        duration_nano: 1_000_000,
        is_root_span: true,
        matched_filter: true,
        attributes: {},
        resource_attributes: {},
        ...overrides,
    }
}
