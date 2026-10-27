import { makeSpan } from './__mocks__/span'
import { buildTraceCallTree } from './traceCallTree'
import type { Span } from './types'

const TRACE_START_MS = Date.parse('2026-09-03T10:00:00.000Z')

function treeSpan(
    id: string,
    parentId: string,
    service_name: string,
    name: string,
    offsetMs: number,
    durationMs: number,
    overrides: Partial<Span> = {}
): Span {
    return makeSpan({
        uuid: id,
        span_id: id,
        parent_span_id: parentId,
        is_root_span: parentId === '',
        service_name,
        name,
        timestamp: new Date(TRACE_START_MS + offsetMs).toISOString(),
        duration_nano: durationMs * 1_000_000,
        ...overrides,
    })
}

describe('buildTraceCallTree', () => {
    it('merges repeated siblings under one parent and keeps the same operation apart under different parents', () => {
        // A tree that merges an operation across its callers gives both "cache GET" nodes a count of 4.
        // The input order differs from the start order, so the test fails if the children sort is dropped.
        const tree = buildTraceCallTree([
            treeSpan('cache-3', 'root', 'web', 'cache GET', 40, 60),
            treeSpan('nested-cache', 'db', 'web', 'cache GET', 3, 5),
            treeSpan('db', 'root', 'db', 'SELECT', 2, 50, { status_code: 2 }),
            treeSpan('root', '', 'web', 'GET /x', 0, 100),
            treeSpan('cache-1', 'root', 'web', 'cache GET', 1, 10),
            treeSpan('cache-2', 'root', 'web', 'cache GET', 15, 20),
        ])

        expect(tree.children.map((child) => child.name)).toEqual(['GET /x'])
        const [getX] = tree.children
        expect(getX.node).toMatchObject({ parent_name: '<ROOT>', count: 1, calls_per_parent_invocation: null })
        expect(getX.children.map((child) => [child.serviceName, child.name])).toEqual([
            ['db', 'SELECT'],
            ['web', 'cache GET'],
        ])
        const [select, cacheGet] = getX.children
        expect(cacheGet.node).toMatchObject({
            parent_service: 'web',
            parent_name: 'GET /x',
            count: 3,
            total_duration_nano: 90_000_000,
            p50_duration_nano: 20_000_000,
            p95_duration_nano: 60_000_000,
            error_count: 0,
            calls_per_parent_invocation: 3,
        })
        expect(select.node).toMatchObject({ error_count: 1 })
        expect(select.children.map((child) => child.node)).toEqual([
            expect.objectContaining({
                parent_name: 'SELECT',
                name: 'cache GET',
                count: 1,
                total_duration_nano: 5_000_000,
            }),
        ])
    })

    // A service that does not export its spans leaves its callees with a parent id that is not in the trace, and a
    // malformed span can name itself as its parent. Both must still show, and the second must not loop the walk.
    it.each([
        { parent: 'a parent that is not in the trace', parentId: 'missing' },
        { parent: 'itself as its parent', parentId: 'orphan' },
    ])('treats a span with $parent as a root', ({ parentId }) => {
        const tree = buildTraceCallTree([treeSpan('orphan', parentId, 'web', 'cache GET', 0, 10)])

        expect(tree.children.map((child) => child.node)).toEqual([
            expect.objectContaining({ parent_name: '<ROOT>', name: 'cache GET', count: 1 }),
        ])
    })

    it('counts calls per parent invocation across several parent spans', () => {
        // Dividing by the one merged "GET /x" node instead of its two spans gives 3, not 1.5.
        const tree = buildTraceCallTree([
            treeSpan('root-1', '', 'web', 'GET /x', 0, 100),
            treeSpan('root-2', '', 'web', 'GET /x', 200, 100),
            treeSpan('cache-1', 'root-1', 'web', 'cache GET', 1, 10),
            treeSpan('cache-2', 'root-1', 'web', 'cache GET', 20, 10),
            treeSpan('cache-3', 'root-2', 'web', 'cache GET', 201, 10),
        ])

        const [getX] = tree.children
        expect(getX.node?.count).toBe(2)
        expect(getX.children.map((child) => child.node)).toEqual([
            expect.objectContaining({ count: 3, calls_per_parent_invocation: 1.5 }),
        ])
    })
})
