import { buildSpanTree, type SpanNode } from 'products/tracing/frontend/spanTree'
import type { Span } from 'products/tracing/frontend/types'

import { buildTraceDialogRows, countDescendantsById, type TraceDialogRow } from './traceDialogRows'

function span(spanId: string, parentSpanId: string, offsetMs: number): Span {
    return {
        uuid: spanId,
        trace_id: 'abc123',
        span_id: spanId,
        parent_span_id: parentSpanId,
        name: spanId,
        kind: 0,
        service_name: 'agent-worker',
        status_code: 0,
        timestamp: new Date(Date.UTC(2026, 9, 14, 10) + offsetMs).toISOString(),
        end_time: new Date(Date.UTC(2026, 9, 14, 10) + offsetMs + 1).toISOString(),
        duration_nano: 1_000_000,
        is_root_span: parentSpanId === '',
        matched_filter: true,
        attributes: {},
        resource_attributes: {},
    }
}

function labels(rows: TraceDialogRow[]): string[] {
    return rows.map((row) => (row.kind === 'span' ? row.node.span.span_id : `+${row.hiddenCount}`))
}

function find(roots: SpanNode[], spanId: string): SpanNode {
    const stack = [...roots]
    while (stack.length > 0) {
        const node = stack.pop()!
        if (node.span.span_id === spanId) {
            return node
        }
        stack.push(...node.children)
    }
    throw new Error(`no span ${spanId}`)
}

describe('traceDialogRows', () => {
    // A root with twelve children in start order, the first of which has a child of its own.
    const roots = buildSpanTree([
        span('root', '', 0),
        ...Array.from({ length: 12 }, (_, i) => span(`c${i}`, 'root', 10 + i)),
        span('g0', 'c0', 11),
    ])
    const firstTen = Array.from({ length: 10 }, (_, i) => `c${i}`)

    it('counts every span under each span', () => {
        const counts = countDescendantsById(roots)

        expect([counts.get('root'), counts.get('c0'), counts.get('c1')]).toEqual([13, 1, 0])
    })

    it.each([
        [
            'caps a wide fan-out with a more row',
            new Set<string>(),
            new Set<string>(),
            null,
            ['root', 'c0', 'g0', ...firstTen.slice(1), '+2'],
        ],
        ['hides a collapsed subtree', new Set(['c0']), new Set<string>(), null, ['root', ...firstTen, '+2']],
        [
            'shows every child once asked',
            new Set<string>(),
            new Set(['root']),
            null,
            ['root', 'c0', 'g0', ...firstTen.slice(1), 'c10', 'c11'],
        ],
        // The span a log came from stays on screen when it sits past the cap.
        [
            'keeps the pinned span past the cap',
            new Set<string>(),
            new Set<string>(),
            'c11',
            ['root', 'c0', 'g0', ...firstTen.slice(1), 'c11', '+1'],
        ],
    ])('%s', (_name, collapsed, fullChildLists, pinnedId, expected) => {
        const pinned = pinnedId ? find(roots, pinnedId) : null

        expect(labels(buildTraceDialogRows(roots, collapsed, fullChildLists, pinned))).toEqual(expected)
    })
})
