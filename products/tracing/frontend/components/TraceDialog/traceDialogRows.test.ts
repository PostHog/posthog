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
    summarizeRun,
    type TraceDialogRow,
    type TraceDialogRowOptions,
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

function opSpan(
    spanId: string,
    parentSpanId: string,
    offsetMs: number,
    name: string,
    serviceName = 'agent-worker'
): Span {
    return { ...span(spanId, parentSpanId, offsetMs), name, service_name: serviceName }
}

function labels(rows: TraceDialogRow[]): string[] {
    return rows.map((row) =>
        row.kind === 'span'
            ? row.node.span.span_id
            : row.kind === 'chain'
              ? `[${row.nodes.map((node) => node.span.span_id).join('>')}]`
              : row.kind === 'run'
                ? `${row.nodes[0].span.span_id}×${row.nodes.length}`
                : row.kind === 'more'
                  ? `+${row.hiddenCount}`
                  : 'fewer'
    )
}

function rowOptions(overrides: Partial<TraceDialogRowOptions> = {}): TraceDialogRowOptions {
    return {
        collapsedSpanIds: new Set(),
        fullChildListSpanIds: new Set(),
        openChainIds: new Set(),
        foldRuns: true,
        openRunIds: new Set(),
        pinned: null,
        ...overrides,
    }
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
        // The full list ends with a row that shortens it again, but only where the cap would shorten it.
        [
            'shows every child once asked',
            new Set<string>(),
            new Set(['root']),
            null,
            ['root', 'c0', 'g0', ...firstTen.slice(1), 'c10', 'c11', 'fewer'],
        ],
        [
            'adds no show fewer row to a full list within the cap',
            new Set<string>(),
            new Set(['c0']),
            null,
            ['root', 'c0', 'g0', ...firstTen.slice(1), '+2'],
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
                buildTraceDialogRows(
                    roots,
                    rowOptions({ collapsedSpanIds: collapsed, fullChildListSpanIds: fullChildLists, pinned })
                )
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
            buildTraceDialogRows(chain, rowOptions({ openChainIds, pinned: pinnedId ? find(chain, pinnedId) : null }))

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
            const rows = buildTraceDialogRows(long, rowOptions({ pinned: find(long, 'a') }))

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
    describe('runs', () => {
        // A root with three cache reads. The second read makes a call of its own.
        const cacheTree = buildSpanTree([
            span('root', '', 0),
            opSpan('cache-1', 'root', 1, 'cache GET'),
            opSpan('cache-2', 'root', 2, 'cache GET'),
            opSpan('redis-1', 'cache-2', 2, 'redis GET'),
            opSpan('cache-3', 'root', 3, 'cache GET'),
        ])
        const opened = ['root', 'cache-1', 'cache-2', 'redis-1', 'cache-3']

        // Fails when a loop of identical calls is listed span by span, when a folded run shows the calls its
        // spans make, or when batches split by another operation merge. The pair on another service shares the
        // name but not the operation.
        it('folds three or more adjacent siblings of one operation, and another operation between them splits the run', () => {
            const tree = buildSpanTree([
                span('root', '', 0),
                opSpan('a1', 'root', 1, 'cache GET'),
                opSpan('a1-call', 'a1', 1, 'redis GET'),
                opSpan('a2', 'root', 2, 'cache GET'),
                opSpan('a3', 'root', 3, 'cache GET'),
                opSpan('select', 'root', 4, 'SELECT'),
                opSpan('b1', 'root', 5, 'cache GET', 'worker'),
                opSpan('b2', 'root', 6, 'cache GET', 'worker'),
                opSpan('c1', 'root', 7, 'cache GET'),
                opSpan('c2', 'root', 8, 'cache GET'),
                opSpan('c3', 'root', 9, 'cache GET'),
            ])

            expect(labels(buildTraceDialogRows(tree, rowOptions()))).toEqual([
                'root',
                'a1×3',
                'select',
                'b1',
                'b2',
                'c1×3',
            ])
        })

        // Fails when a deep link lands on a span that a folded run hides, when a run that only the pin holds
        // open offers a fold control that would change nothing, or when a run folds with the flag off.
        it.each([
            { state: 'no state', options: {}, expected: ['root', 'cache-1×3'], openRunLength: undefined },
            {
                state: 'its id in openRunIds',
                options: { openRunIds: new Set(['cache-1']) },
                expected: opened,
                openRunLength: 3,
            },
            {
                state: 'the pin under one of its spans',
                options: { pinned: find(cacheTree, 'redis-1') },
                expected: opened,
                openRunLength: undefined,
            },
            {
                state: 'a collapsed parent',
                options: { collapsedSpanIds: new Set(['root']) },
                expected: ['root'],
                openRunLength: undefined,
            },
            {
                state: 'folding turned off',
                options: { foldRuns: false },
                expected: opened,
                openRunLength: undefined,
            },
        ])('with $state, lists the run as expected', ({ options, expected, openRunLength }) => {
            const rows = buildTraceDialogRows(cacheTree, rowOptions(options))

            expect(labels(rows)).toEqual(expected)
            expect(rows[1]?.kind === 'span' ? rows[1].openRunLength : undefined).toEqual(openRunLength)
        })

        it('never folds missing-parent placeholders, so each orphaned span keeps its own row', () => {
            const tree = buildSpanTree([1, 2, 3].map((i) => opSpan(`orphan-${i}`, `gone-${i}`, i, 'GET /x')))

            expect(labels(buildTraceDialogRows(tree, rowOptions()))).toEqual([
                'gone-1',
                'orphan-1',
                'gone-2',
                'orphan-2',
                'gone-3',
                'orphan-3',
            ])
        })

        // Fails when the cap counts spans before the fold, which shows ten reads of a run of thousands and a
        // "more" row for the rest, when the "more" row counts a hidden run as one span, or when the cap stops
        // counting spans with folding turned off.
        it.each([
            {
                folding: 'on',
                foldRuns: true,
                expected: ['root', 'get0×20', ...Array.from({ length: 9 }, (_, i) => `d${i}`), '+5'],
            },
            {
                folding: 'off',
                foldRuns: false,
                expected: ['root', ...Array.from({ length: 10 }, (_, i) => `get${i}`), '+24'],
            },
        ])(
            'with folding $folding, caps the rows after the fold, and the more row counts the spans it hides',
            ({ foldRuns, expected }) => {
                const tree = buildSpanTree([
                    span('root', '', 0),
                    ...Array.from({ length: 20 }, (_, i) => opSpan(`get${i}`, 'root', 1 + i, 'cache GET')),
                    ...Array.from({ length: 9 }, (_, i) => span(`d${i}`, 'root', 30 + i)),
                    ...Array.from({ length: 5 }, (_, i) => opSpan(`put${i}`, 'root', 40 + i, 'cache PUT')),
                ])

                expect(labels(buildTraceDialogRows(tree, rowOptions({ foldRuns })))).toEqual(expected)
            }
        )

        // Fails when an opened run takes ten items of the cap, which hides the spans after it behind a more row.
        it('counts an opened run as one item of the cap and lists all of its spans', () => {
            const tree = buildSpanTree([
                span('root', '', 0),
                ...Array.from({ length: 20 }, (_, i) => opSpan(`get${i}`, 'root', 1 + i, 'cache GET')),
                ...Array.from({ length: 3 }, (_, i) => span(`d${i}`, 'root', 30 + i)),
            ])

            expect(labels(buildTraceDialogRows(tree, rowOptions({ openRunIds: new Set(['get0']) })))).toEqual([
                'root',
                ...Array.from({ length: 20 }, (_, i) => `get${i}`),
                'd0',
                'd1',
                'd2',
            ])
        })

        // Fails when the run's bar ends at its last span's end, which cuts off an earlier span that outlasts it, or
        // when an error two levels under the run's spans goes uncounted, which the folded run would hide.
        it('summarizes a run from the first start to the latest end', () => {
            const tree = buildSpanTree([
                span('root', '', 0),
                { ...opSpan('long', 'root', 1, 'cache GET'), duration_nano: 10_000_000, status_code: 2 },
                opSpan('short-1', 'root', 2, 'cache GET'),
                opSpan('short-2', 'root', 3, 'cache GET'),
                span('retry', 'short-1', 2),
                { ...span('socket', 'retry', 2), status_code: 2 },
            ])
            const start = Date.UTC(2026, 9, 14, 10) * 1_000

            expect(summarizeRun(tree[0].children)).toEqual({
                startUs: start + 1_000,
                endUs: start + 11_000,
                totalDurationNano: 12_000_000,
                errorCount: 1,
                nestedErrorCount: 1,
            })
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
        { hiddenBy: 'a folded run', spanId: 'q', collapsed: [], reveal: { runIds: ['l0'] } },
        { hiddenBy: 'nested folded runs', spanId: 'z', collapsed: [], reveal: { runIds: ['l0', 'r0'] } },
        {
            hiddenBy: 'a folded run past the child cap',
            spanId: 'w',
            collapsed: [],
            reveal: { fullChildListSpanIds: ['root'], runIds: ['t0'] },
        },
        // The folded run row stands for its first span and carries the operation's name.
        { hiddenBy: 'nothing, as the first span of a folded run', spanId: 'loop', collapsed: [], reveal: {} },
        // The cap counts a folded run as one item, so the span is the eleventh child but only the ninth item.
        {
            hiddenBy: 'nothing, as a span that a folded run keeps inside the cap',
            spanId: 's6',
            collapsed: [],
            reveal: {},
        },
    ])('reveals a span hidden by $hiddenBy', ({ spanId, collapsed, reveal }) => {
        // The root fans out to x, c0 to c11 and a run of three tail spans, so c9 to c11 and the run sit past the
        // cap. The second tail span has a child w. c11 fans out to d0 to d11 in turn. c0 has a child g0, a run of
        // three loop spans and s0 to s6. The second loop span has a child q and a run of three inner spans, the
        // second of which has a child z. x > a > b > c > d folds a to c into a chain.
        const tree = buildSpanTree([
            span('root', '', 0),
            span('x', 'root', 5),
            ...Array.from({ length: 12 }, (_, i) => span(`c${i}`, 'root', 10 + i)),
            ...Array.from({ length: 12 }, (_, i) => span(`d${i}`, 'c11', 30 + i)),
            span('g0', 'c0', 11),
            ...[0, 1, 2].map((i) => opSpan(`l${i}`, 'c0', 12 + i, 'loop')),
            span('q', 'l1', 13),
            ...[0, 1, 2].map((i) => opSpan(`r${i}`, 'l1', 14 + i, 'inner')),
            span('z', 'r1', 15),
            ...Array.from({ length: 7 }, (_, i) => span(`s${i}`, 'c0', 20 + i)),
            ...[0, 1, 2].map((i) => opSpan(`t${i}`, 'root', 25 + i, 'tail')),
            span('w', 't1', 26),
            span('a', 'x', 6),
            span('b', 'a', 7),
            span('c', 'b', 8),
            span('d', 'c', 9),
        ])
        const target = firstOperationSpan(tree, compareRowKey({ service_name: 'agent-worker', name: spanId }))

        expect(revealSpanInRows(tree, target!, rowOptions({ collapsedSpanIds: new Set(collapsed) }))).toEqual({
            collapsedSpanIds: [],
            fullChildListSpanIds: [],
            chainIds: [],
            runIds: [],
            ...reveal,
        })
    })
    // Fails when a row that hides a span of the operation dims, which tells the person the operation is not in
    // there, or when a collapsed span lights up for a match it does not hold.
    it.each([
        { row: 'a collapsed span with a match under it', label: 'c0', operation: 'g0', matches: true },
        { row: 'a collapsed span with no match under it', label: 'c0', operation: 'c1', matches: false },
        { row: 'a more row with a match under a hidden child', label: '+2', operation: 'h', matches: true },
        { row: 'a folded run of the operation', label: 'l0×3', operation: 'loop', matches: true },
        { row: 'a folded run with a match under one of its spans', label: 'l0×3', operation: 'm', matches: true },
        { row: 'a folded run with no match in it', label: 'l0×3', operation: 'g0', matches: false },
    ])('matches $row: $matches', ({ label, operation, matches }) => {
        // The root fans out to c0 to c11, so c10 and c11 sit past the cap. c0 has a child g0, and c11 has h.
        // c1 has a run of three loop spans, and the last one has a child m.
        const tree = buildSpanTree([
            span('root', '', 0),
            ...Array.from({ length: 12 }, (_, i) => span(`c${i}`, 'root', 10 + i)),
            span('g0', 'c0', 11),
            ...[0, 1, 2].map((i) => opSpan(`l${i}`, 'c1', 12 + i, 'loop')),
            span('m', 'l2', 15),
            span('h', 'c11', 22),
        ])
        const collapsedSpanIds = new Set(['c0'])
        const rows = buildTraceDialogRows(tree, rowOptions({ collapsedSpanIds }))
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
