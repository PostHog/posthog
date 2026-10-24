import { compareRowKey } from 'products/tracing/frontend/compareUtils'
import { buildSpanTree, type SpanNode } from 'products/tracing/frontend/spanTree'
import type { Span } from 'products/tracing/frontend/types'

import {
    buildTraceDialogRows,
    countDescendantsById,
    firstOperationSpan,
    markOperationSubtrees,
    operationRowMatches,
    revealSpanInRows,
    rowConnectorLines,
    type TraceDialogRow,
} from './traceDialogRows'

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
    return rows.map((row) =>
        row.kind === 'span'
            ? row.node.span.span_id
            : row.kind === 'chain'
              ? `[${row.nodes.map((node) => node.span.span_id).join('>')}]`
              : `+${row.hiddenCount}`
    )
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

        expect(
            labels(
                buildTraceDialogRows(roots, {
                    collapsedSpanIds: collapsed,
                    fullChildListSpanIds: fullChildLists,
                    openChainIds: new Set(),
                    pinned,
                })
            )
        ).toEqual(expected)
    })

    describe('chains', () => {
        // root > a > b > c > d, where d branches into e and f.
        const chain = buildSpanTree([
            span('root', '', 0),
            span('a', 'root', 1),
            span('b', 'a', 2),
            span('c', 'b', 3),
            span('d', 'c', 4),
            span('e', 'd', 5),
            span('f', 'd', 6),
        ])
        const build = (openChainIds: Set<string>, pinnedId: string | null = null): TraceDialogRow[] =>
            buildTraceDialogRows(chain, {
                collapsedSpanIds: new Set(),
                fullChildListSpanIds: new Set(),
                openChainIds,
                pinned: pinnedId ? find(chain, pinnedId) : null,
            })

        it.each([
            [
                'folds a run of single-child spans into one row',
                new Set<string>(),
                null,
                ['root', '[a>b>c]', 'd', 'e', 'f'],
            ],
            // Opening must not fold the rest of the run again from its second span.
            ['shows every span of an opened chain', new Set(['a']), null, ['root', 'a', 'b', 'c', 'd', 'e', 'f']],
            [
                'keeps the chain open when the span a log came from is inside it',
                new Set<string>(),
                'b',
                ['root', 'a', 'b', 'c', 'd', 'e', 'f'],
            ],
        ])('%s', (_name, openChainIds, pinnedId, expected) => {
            expect(labels(build(openChainIds, pinnedId))).toEqual(expected)
        })

        it('still folds the spans below the span a log came from', () => {
            const long = buildSpanTree([
                span('root', '', 0),
                span('a', 'root', 1),
                span('b', 'a', 2),
                span('c', 'b', 3),
                span('d', 'c', 4),
                span('e', 'd', 5),
                span('f', 'e', 6),
            ])
            const rows = buildTraceDialogRows(long, {
                collapsedSpanIds: new Set(),
                fullChildListSpanIds: new Set(),
                openChainIds: new Set(),
                pinned: find(long, 'a'),
            })

            expect(labels(rows)).toEqual(['root', 'a', '[b>c>d>e]', 'f'])
        })

        it('places rows under a folded chain one level below it, with lines only where siblings follow', () => {
            const rows = build(new Set())
            const [, chainRow, d, e, f] = rows

            expect([chainRow.depth, d.depth, e.depth, f.depth]).toEqual([1, 2, 3, 3])
            expect([e.isLast, f.isLast]).toEqual([false, true])
            expect(rowConnectorLines(f)).toEqual([false, false])
        })
    })
    // Fails when the highlight leaves the operation's first span hidden, so the tree has no row to scroll to,
    // or when it toggles something that was already open and hides more of the tree instead.
    it.each([
        { hiddenBy: 'the child cap', spanId: 'c11', collapsed: [], reveal: { fullChildListSpanIds: ['root'] } },
        {
            hiddenBy: 'nested child caps',
            spanId: 'd11',
            collapsed: [],
            reveal: { fullChildListSpanIds: ['root', 'c11'] },
        },
        { hiddenBy: 'a collapsed span', spanId: 'g0', collapsed: ['c0'], reveal: { collapsedSpanIds: ['c0'] } },
        { hiddenBy: 'a folded chain', spanId: 'b', collapsed: [], reveal: { chainIds: ['a'] } },
        { hiddenBy: 'nothing, as the head of a folded chain', spanId: 'a', collapsed: [], reveal: {} },
    ])('reveals a span hidden by $hiddenBy', ({ spanId, collapsed, reveal }) => {
        // The root fans out to x and c0 to c11, so c9 to c11 sit past the cap. c11 fans out to d0 to d11 in
        // turn. c0 has a child g0, and x > a > b > c > d folds a to c into a chain.
        const tree = buildSpanTree([
            span('root', '', 0),
            span('x', 'root', 5),
            ...Array.from({ length: 12 }, (_, i) => span(`c${i}`, 'root', 10 + i)),
            ...Array.from({ length: 12 }, (_, i) => span(`d${i}`, 'c11', 30 + i)),
            span('g0', 'c0', 11),
            span('a', 'x', 6),
            span('b', 'a', 7),
            span('c', 'b', 8),
            span('d', 'c', 9),
        ])
        const target = firstOperationSpan(tree, compareRowKey({ service_name: 'agent-worker', name: spanId }))

        expect(
            revealSpanInRows(tree, target!, {
                collapsedSpanIds: new Set(collapsed),
                fullChildListSpanIds: new Set(),
                openChainIds: new Set(),
                pinned: null,
            })
        ).toEqual({ collapsedSpanIds: [], fullChildListSpanIds: [], chainIds: [], ...reveal })
    })
    // Fails when a row that hides a span of the operation dims, which tells the person the operation is not in
    // there, or when a collapsed span lights up for a match it does not hold.
    it.each([
        { row: 'a collapsed span with a match under it', label: 'c0', operation: 'g0', matches: true },
        { row: 'a collapsed span with no match under it', label: 'c0', operation: 'c1', matches: false },
        { row: 'a more row with a match under a hidden child', label: '+2', operation: 'h', matches: true },
    ])('matches $row: $matches', ({ label, operation, matches }) => {
        // The root fans out to c0 to c11, so c10 and c11 sit past the cap. c0 has a child g0, and c11 has h.
        const tree = buildSpanTree([
            span('root', '', 0),
            ...Array.from({ length: 12 }, (_, i) => span(`c${i}`, 'root', 10 + i)),
            span('g0', 'c0', 11),
            span('h', 'c11', 22),
        ])
        const collapsedSpanIds = new Set(['c0'])
        const rows = buildTraceDialogRows(tree, {
            collapsedSpanIds,
            fullChildListSpanIds: new Set(),
            openChainIds: new Set(),
            pinned: null,
        })
        const operationKey = compareRowKey({ service_name: 'agent-worker', name: operation })

        const rowMatches = operationRowMatches(
            rows,
            operationKey,
            markOperationSubtrees(tree, operationKey),
            collapsedSpanIds
        )

        expect(rowMatches[labels(rows).indexOf(label)]).toBe(matches)
    })
})
