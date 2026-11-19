import { buildSpanTree, collectCollapsibleSpanIds, connectorLinesOf, countDescendants, flattenTree } from './spanTree'
import type { Span } from './types'

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

describe('spanTree', () => {
    it('flattens depth first with children in start order', () => {
        const tree = buildSpanTree([
            span('root', '', 0),
            span('late', 'root', 20),
            span('early', 'root', 10),
            span('grandchild', 'early', 15),
        ])

        expect(flattenTree(tree, new Set()).map((node) => [node.span.span_id, node.depth, node.isLastChild])).toEqual([
            ['root', 0, true],
            ['early', 1, false],
            ['grandchild', 2, true],
            ['late', 1, true],
        ])
        expect(flattenTree(tree, new Set(['early'])).map((node) => node.span.span_id)).toEqual([
            'root',
            'early',
            'late',
        ])
        expect(connectorLinesOf(tree[0].children[0].children[0])).toEqual([false, true])
    })

    it('handles a parent/child chain deeper than the call stack', () => {
        const depth = 20_000
        const spans = Array.from({ length: depth }, (_, i) => span(`s${i}`, i === 0 ? '' : `s${i - 1}`, i))

        const tree = buildSpanTree(spans)
        const flat = flattenTree(tree, new Set())

        expect(flat).toHaveLength(depth)
        expect(flat[depth - 1].depth).toBe(depth - 1)
        expect(countDescendants(tree[0])).toBe(depth - 1)
        expect(collectCollapsibleSpanIds(tree).size).toBe(depth - 1)
    })
})
