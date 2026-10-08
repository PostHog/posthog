import { traceRows } from './traceRows'
import type { Span } from './types'

function span(overrides: Partial<Span>): Span {
    return {
        uuid: overrides.span_id ?? 'u',
        trace_id: 'trace-1',
        span_id: 'span-1',
        parent_span_id: '',
        name: 'op',
        kind: 2,
        service_name: 'svc',
        status_code: 0,
        timestamp: '2026-06-02T08:00:00.000Z',
        end_time: '2026-06-02T08:00:01.000Z',
        duration_nano: 1e9,
        is_root_span: false,
        matched_filter: true,
        attributes: {},
        resource_attributes: {},
        ...overrides,
    }
}

const rootA = span({ trace_id: 'a', span_id: 'a1', is_root_span: true, trace_start: '2026-06-02T08:00:00.000Z' })
const rootC = span({ trace_id: 'c', span_id: 'c1', is_root_span: true, trace_start: '2026-06-02T08:00:02.000Z' })
// Trace b: its parent `upstream` was never received.
const orphanTop = span({
    trace_id: 'b',
    span_id: 'b1',
    parent_span_id: 'upstream',
    timestamp: '2026-06-02T08:00:01.000Z',
    trace_start: '2026-06-02T08:00:01.000Z',
})
const orphanChild = span({
    trace_id: 'b',
    span_id: 'b2',
    parent_span_id: 'b1',
    timestamp: '2026-06-02T08:00:00.500Z',
    trace_start: '2026-06-02T08:00:01.000Z',
})

describe('traceRows', () => {
    it('returns root spans as-is when every trace has a root', () => {
        const child = span({ trace_id: 'a', span_id: 'a2', parent_span_id: 'a1' })
        expect(traceRows([rootA, rootC, child], 'timestamp', 'DESC')).toEqual([rootA, rootC])
    })

    it('promotes the top span of a trace with no root, even if a child started earlier', () => {
        const rows = traceRows([rootA, orphanChild, orphanTop], 'timestamp', 'ASC')
        expect(rows.map((s) => s.span_id)).toEqual(['a1', 'b1'])
        expect(rows[1].root_missing).toBe(true)
    })

    it.each([
        ['ASC', ['a1', 'b1', 'c1']],
        ['DESC', ['c1', 'b1', 'a1']],
    ] as const)('puts promoted rows in trace order (%s)', (direction, expected) => {
        const rows = traceRows([rootC, rootA, orphanTop, orphanChild], 'timestamp', direction)
        expect(rows.map((s) => s.span_id)).toEqual(expected)
    })

    it('orders by trace duration under duration sort', () => {
        const rows = traceRows(
            [
                { ...rootA, trace_duration: 5 },
                { ...orphanTop, trace_duration: 9 },
            ],
            'duration',
            'DESC'
        )
        expect(rows.map((s) => s.span_id)).toEqual(['b1', 'a1'])
    })
})
