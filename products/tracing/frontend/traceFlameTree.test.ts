import { SpanTreeNode } from '~/queries/schema/schema-general'

import { findFlamePath } from './flameTree'
import { buildTree, flameIdOf, toFlameNodes } from './traceFlameTree'

const COMPARE = { sizeBy: 'p50', hasBaseline: true } as const
const SINGLE_TRACE = { sizeBy: 'total', hasBaseline: false, errorColor: 'red' } as const

const edge = (
    parent: string | null,
    name: string,
    p50: number,
    count = 100,
    overrides: Partial<SpanTreeNode> = {}
): SpanTreeNode => ({
    parent_service: parent ? 'api' : '',
    parent_name: parent ?? '<ROOT>',
    service_name: 'api',
    name,
    count,
    total_duration_nano: p50 * count,
    avg_duration_nano: p50,
    p50_duration_nano: p50,
    p95_duration_nano: p50 * 2,
    p99_duration_nano: p50 * 3,
    p999_duration_nano: p50 * 4,
    error_count: 0,
    avg_start_offset_nano: 0,
    ...overrides,
})

describe('traceFlameTree', () => {
    it('maps both windows onto value and baseline, keeping new and vanished spans', () => {
        const current = [
            edge(null, 'root', 100),
            edge('root', 'kept', 40),
            edge('root', 'new', 10),
            edge('root', 'instant', 0),
            edge('root', 'was-instant', 50),
        ]
        const previous = [
            edge(null, 'root', 80),
            edge('root', 'kept', 50),
            edge('root', 'gone', 20),
            edge('root', 'instant', 30),
            edge('root', 'was-instant', 0),
        ]
        const [root] = toFlameNodes(buildTree(current, previous), COMPARE)
        const byName = Object.fromEntries((root.children ?? []).map((child) => [child.name, child]))

        expect(root).toMatchObject({ value: 100, baselineValue: 80, count: 100, baselineCount: 100, group: 'api' })
        expect(byName.kept).toMatchObject({ value: 40, baselineValue: 50 })
        expect(byName.new).toMatchObject({ value: 10, baselineValue: 0 })
        expect(byName.gone).toMatchObject({ value: 0, baselineValue: 20, count: undefined })
        expect(byName.instant).toMatchObject({ value: 1, baselineValue: 30 })
        expect(byName['was-instant']).toMatchObject({ value: 50, baselineValue: 50 })
    })

    it('draws a single trace by total time, with span counts and errors and no baseline', () => {
        const [root] = toFlameNodes(buildTree([edge(null, 'root', 100, 3, { error_count: 1 })], null), SINGLE_TRACE)
        expect(root).toMatchObject({ name: 'root ×3', value: 300, color: 'red' })
        expect(root.baselineValue).toBeUndefined()
        expect(root.baselineCount).toBeUndefined()
    })

    it('merges a span reached from two parents with a count-weighted median', () => {
        const current = [
            edge(null, 'a', 10),
            edge(null, 'b', 10),
            edge('a', 'shared', 5, 900),
            edge('b', 'shared', 500, 100),
        ]
        const [a] = toFlameNodes(buildTree(current, null), COMPARE)
        expect(a.children?.[0]).toMatchObject({ name: 'shared', value: 5, count: 1000 })
    })

    it('stops at a cycle and finds the initial span by the id the flame graph uses', () => {
        const current = [edge(null, 'A', 10), edge('A', 'B', 5), edge('B', 'A', 2)]
        const tree = buildTree(current, null)
        const [a] = toFlameNodes(tree, COMPARE)
        expect(a.children?.[0].name).toBe('B')
        expect(a.children?.[0].children).toEqual([])
        expect(flameIdOf(findFlamePath(tree, (node) => node.name === 'B')!)).toBe(a.children?.[0].id)
    })
})
