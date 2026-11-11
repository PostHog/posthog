import { groupBy } from 'lib/utils/arrays'

import type { HogFlowAction, HogFlowEdge } from '../../types'
import { Box, CanvasLayout, layoutTileCanvas, NodeSize, pathFrameSpecs } from './tileCanvasLayout'
import { computePathGroups, computeVisibleGraph, FlowGraph, PathGroup, Point, VisibleEdge } from './tileCanvasModel'

const step = (id: string, type: HogFlowAction['type'] = 'function'): HogFlowAction =>
    ({ id, type, name: id, description: '', config: {} }) as HogFlowAction

const pathEdge = (from: string, to: string, index: number, count: number): HogFlowEdge =>
    index < count - 1 ? { from, to, type: 'branch', index } : { from, to, type: 'continue' }

/** A split whose paths hold two steps each, and one step for an arm in `single`, and join again at `join`. */
function fanOut(
    split: string,
    arms: string[],
    join: string,
    single: string[] = []
): { actions: HogFlowAction[]; edges: HogFlowEdge[] } {
    const stepsOf = (arm: string): string[] => (single.includes(arm) ? [`${arm}1`] : [`${arm}1`, `${arm}2`])
    return {
        actions: [step(split, 'conditional_branch'), ...arms.flatMap((arm) => stepsOf(arm).map((id) => step(id)))],
        edges: arms.flatMap((arm, index) => {
            const ids = stepsOf(arm)
            return [
                pathEdge(split, ids[0], index, arms.length),
                ...ids.slice(1).map((id, at): HogFlowEdge => ({ from: ids[at], to: id, type: 'continue' })),
                { from: ids[ids.length - 1], to: join, type: 'continue' },
            ]
        }),
    }
}

const OUTER = ['a', 'b', 'c', 'd', 'e', 'f']
const INNER = ['x', 'y', 'z']

// trigger -> split with six paths; the middle path starts with its own three-way split, and the last holds one step
const outer = fanOut('split', OUTER, 'exit', ['f'])
const inner = fanOut('c1', INNER, 'c2')
const workflow = {
    actions: [
        step('trigger', 'trigger'),
        ...outer.actions.map((action) => (action.id === 'c1' ? step('c1', 'conditional_branch') : action)),
        ...inner.actions.filter((action) => action.id !== 'c1'),
        step('exit', 'exit'),
    ],
    edges: [
        { from: 'trigger', to: 'split', type: 'continue' } as HogFlowEdge,
        ...outer.edges.filter((edge) => edge.from !== 'c1'),
        ...inner.edges,
    ],
}

const groups = computePathGroups(workflow)
const outerArms = groups.filter((group) => group.branchActionId === 'split')
const innerArms = groups.filter((group) => group.branchActionId === 'c1')

const STEP: NodeSize = { width: 260, height: 64, anchor: { x: 32, y: 32, width: 64, height: 64 } }
const STACK: NodeSize = { width: 180, height: 90, anchor: { x: 40, y: 40, width: 80, height: 80 } }

async function layOut(
    flow: FlowGraph,
    flowGroups: PathGroup[],
    openIds: string[],
    stopIfStale?: () => void
): Promise<{ layout: CanvasLayout; sizes: Record<string, NodeSize>; edges: VisibleEdge[] }> {
    const graph = computeVisibleGraph(flow, flowGroups, openIds)
    const sizes: Record<string, NodeSize> = Object.fromEntries(
        graph.nodes.map((node) => [node.id, node.kind === 'stack' ? STACK : STEP])
    )
    const frames = pathFrameSpecs(flowGroups, openIds, graph.nodes)
    const layout = await layoutTileCanvas(sizes, graph.edges, frames, stopIfStale)
    return { layout, sizes, edges: graph.edges }
}

async function layoutWith(openIds: string[]): Promise<(group: PathGroup) => { x: number; top: number }> {
    const { layout, sizes } = await layOut(workflow, groups, openIds)
    return (group) => {
        const frame = layout.frames[`frame:${group.id}`]
        return frame
            ? { x: frame.x + frame.width / 2, top: frame.y }
            : { x: layout.positions[group.id].x + sizes[group.id].width / 2, top: layout.positions[group.id].y }
    }
}

/** The arms of a split from left to right, by the centre of each one's stack or open frame. */
async function leftToRight(arms: PathGroup[], openIds: string[]): Promise<string[]> {
    const placeOf = await layoutWith(openIds)
    return [...arms].sort((one, other) => placeOf(one).x - placeOf(other).x).map((group) => group.memberIds[0])
}

const sharedTarget: FlowGraph = {
    actions: ['trigger', 'split', 'b1', 'b2', 'b3', 'shared', 'd1', 'd2', 'd3', 'after', 'join', 'exit'].map((id) =>
        step(id, id === 'trigger' ? 'trigger' : id === 'split' ? 'conditional_branch' : 'function')
    ),
    edges: [
        { from: 'trigger', to: 'split', type: 'continue' },
        ...['shared', 'shared', 'b1', 'shared', 'd1'].map((to, index) => pathEdge('split', to, index, 5)),
        ...[
            ['b1', 'b2'],
            ['b2', 'b3'],
            ['b3', 'join'],
            ['d1', 'd2'],
            ['d2', 'd3'],
            ['d3', 'join'],
            ['shared', 'after'],
            ['after', 'exit'],
            ['join', 'exit'],
        ].map(([from, to]): HogFlowEdge => ({ from, to, type: 'continue' })),
    ],
}
const sharedTargetGroups = computePathGroups(sharedTarget)

const splits = (from: [string, string[]][]): HogFlowEdge[] =>
    from.flatMap(([source, targets]) => targets.map((to, index) => pathEdge(source, to, index, targets.length)))

// Splits that lead into each other, so opening the first path moves the targets of the splits below it
const nestedSplits: FlowGraph = {
    actions: ['n0', 'n1', 'n2', 'n3', 'n4', 'n5', 'n6', 'n7'].map((id) =>
        step(id, id === 'n0' ? 'trigger' : ['n6', 'n7'].includes(id) ? 'function' : 'conditional_branch')
    ),
    edges: [
        { from: 'n0', to: 'n1', type: 'continue' },
        ...splits([
            ['n1', ['n2', 'n2', 'n5']],
            ['n2', ['n3', 'n7']],
            ['n3', ['n4', 'n5']],
            ['n4', ['n5', 'n6', 'n6']],
            ['n5', ['n6', 'n6']],
        ]),
        { from: 'n6', to: 'n7', type: 'continue' },
    ],
}
const nestedSplitsGroups = computePathGroups(nestedSplits)

const longDrop: FlowGraph = {
    actions: ['n0', 'n1', 'n2', 'n3', 'n4', 'n5', 'n6'].map((id) =>
        step(id, id === 'n0' ? 'trigger' : id === 'n6' ? 'function' : 'conditional_branch')
    ),
    edges: [
        { from: 'n0', to: 'n1', type: 'continue' },
        ...splits([
            ['n1', ['n2', 'n2', 'n5']],
            ['n2', ['n3', 'n3', 'n4', 'n3']],
            ['n3', ['n4', 'n5', 'n6']],
            ['n4', ['n5', 'n5']],
            ['n5', ['n6']],
        ]),
    ],
}

const TEN = Array.from({ length: 10 }, (_, index) => `p${index}`)
const busyJoin: FlowGraph = {
    actions: [
        step('trigger', 'trigger'),
        step('split', 'conditional_branch'),
        ...TEN.map((id) => step(id)),
        step('exit'),
    ],
    edges: [
        { from: 'trigger', to: 'split', type: 'continue' },
        ...splits([['split', TEN]]),
        ...TEN.map((id): HogFlowEdge => ({ from: id, to: 'exit', type: 'continue' })),
    ],
}

const laterCross: FlowGraph = {
    actions: ['n0', 'n1', 'n2', 'n3', 'n4', 'n5', 'n6', 'n7', 'n8', 'n9'].map((id) =>
        step(id, id === 'n0' ? 'trigger' : id === 'n9' ? 'function' : 'conditional_branch')
    ),
    edges: [
        { from: 'n0', to: 'n1', type: 'continue' },
        ...splits([
            ['n1', ['n2', 'n7', 'n2']],
            ['n2', ['n3', 'n3', 'n4', 'n3']],
            ['n3', ['n4', 'n4', 'n9', 'n8']],
            ['n4', ['n5', 'n5', 'n7', 'n5']],
            ['n5', ['n6', 'n8', 'n7', 'n6']],
            ['n6', ['n7', 'n7', 'n8', 'n7']],
            ['n7', ['n8', 'n8', 'n9', 'n8']],
            ['n8', ['n9', 'n9', 'n9', 'n9']],
        ]),
    ],
}

type Segment = [Point, Point]
const segmentsOf = (points: Point[]): Segment[] => points.slice(1).map((end, index) => [points[index], end])
const span = (a: number, b: number): [number, number] => [Math.min(a, b), Math.max(a, b)]

function overlap([a0, a1]: Segment, [b0, b1]: Segment): number {
    const axis =
        a0.y === a1.y && b0.y === b1.y && a0.y === b0.y
            ? 'x'
            : a0.x === a1.x && b0.x === b1.x && a0.x === b0.x
              ? 'y'
              : null
    if (!axis) {
        return 0
    }
    const [aLow, aHigh] = span(a0[axis], a1[axis])
    const [bLow, bHigh] = span(b0[axis], b1[axis])
    return Math.min(aHigh, bHigh) - Math.max(aLow, bLow)
}

function crosses(one: Segment, other: Segment): boolean {
    const [across, down] = one[0].y === one[1].y ? [one, other] : [other, one]
    const [left, right] = span(across[0].x, across[1].x)
    const [top, bottom] = span(down[0].y, down[1].y)
    const { x } = down[0]
    const { y } = across[0]
    return down[1].x === x && across[1].y === y && x > left && x < right && y > top && y < bottom
}

const pairsOf = <T>(items: T[]): [T, T][] =>
    items.flatMap((one, index) => items.slice(index + 1).map((other): [T, T] => [one, other]))

const OUTER_ORDER = OUTER.slice(0, -1).map((arm) => `${arm}1`)
const INNER_ORDER = INNER.map((arm) => `${arm}1`)

describe('layoutTileCanvas', () => {
    it.each([
        ['nothing open', [] as PathGroup[], outerArms, OUTER_ORDER],
        ['the middle path open', [outerArms[2]], outerArms, OUTER_ORDER],
        ['the middle path open, for its inner paths', [outerArms[2]], innerArms, INNER_ORDER],
        ['an inner path open', [outerArms[2], innerArms[1]], outerArms, OUTER_ORDER],
        ['an inner path open, for its inner paths', [outerArms[2], innerArms[1]], innerArms, INNER_ORDER],
    ])('keeps each path between the same neighbours with %s', async (_, open, arms, expected) => {
        expect(
            await leftToRight(
                arms,
                open.map((group) => group.id)
            )
        ).toEqual(expected)
    })

    it.each([
        ['a path of plain steps', 1],
        ['a path with paths of its own', 2],
    ])('keeps the other paths level with %s that opens', async (_, opened) => {
        const placeOf = await layoutWith([outerArms[opened].id])
        const tops = outerArms.map((arm) => placeOf(arm).top)

        expect(tops).toEqual(tops.map(() => placeOf(outerArms[opened]).top))
    })

    it.each([
        ['a split into a shared step, closed', sharedTarget, sharedTargetGroups, [] as string[]],
        ['a split into a shared step, open', sharedTarget, sharedTargetGroups, sharedTargetGroups.map((g) => g.id)],
        [
            'splits that lead into each other, with the first path open',
            nestedSplits,
            nestedSplitsGroups,
            ['path:n2:branch:0'],
        ],
        ['an arrow that turns only near its target', longDrop, computePathGroups(longDrop), [] as string[]],
        ['arrows that cross below the nearest target', laterCross, computePathGroups(laterCross), [] as string[]],
    ])(
        'gives each arrow of a split its own line, with its label on it, for %s',
        async (_, flow, flowGroups, openIds) => {
            const { layout, sizes, edges } = await layOut(flow, flowGroups, openIds)
            const routes = Object.values(layout.edges)
            const routed = (from: VisibleEdge[]): [string, CanvasLayout['edges'][string]][] =>
                from.filter(({ id }) => layout.edges[id]).map(({ id }) => [id, layout.edges[id]])
            const fromSplits = Object.values(groupBy(edges, (edge) => edge.source)).filter((group) => group.length > 1)

            const sharedRuns = pairsOf(routes).filter(([one, other]) =>
                segmentsOf(one.points).some((a) => segmentsOf(other.points).some((b) => overlap(a, b) > 1))
            )
            const splitCrossings = fromSplits.flatMap((group) =>
                pairsOf(routed(group))
                    .filter(([[, one], [, other]]) =>
                        segmentsOf(one.points).some((a) => segmentsOf(other.points).some((b) => crosses(a, b)))
                    )
                    .map(([[one], [other]]) => [one, other])
            )
            const onLine = (label: Point, [a, b]: Segment): boolean =>
                a.x === b.x &&
                Math.abs(a.x - label.x) < 1 &&
                label.y >= span(a.y, b.y)[0] &&
                label.y <= span(a.y, b.y)[1]
            const labelsOffTheirLine = routed(fromSplits.flat())
                .filter(
                    ([, { label, points }]) => !label || !segmentsOf(points).some((segment) => onLine(label, segment))
                )
                .map(([id]) => id)

            const meetsTile = (point: Point | undefined, node: string): boolean => {
                const { x, width } = sizes[node].anchor as Box
                return !!point && Math.abs(point.x - layout.positions[node].x - x) < width / 2
            }
            const arrowsOffTheirTiles = edges
                .filter(({ id, source, target }) => {
                    const points = layout.edges[id]?.points
                    return !meetsTile(points?.[0], source) || !meetsTile(points?.at(-1), target)
                })
                .map(({ id }) => id)

            expect({
                unrouted: edges.filter(({ id }) => !layout.edges[id]).map(({ id }) => id),
                sharedRuns,
                splitCrossings,
                labelsOffTheirLine,
                arrowsOffTheirTiles,
            }).toEqual({
                unrouted: [],
                sharedRuns: [],
                splitCrossings: [],
                labelsOffTheirLine: [],
                arrowsOffTheirTiles: [],
            })
        }
    )

    it('keeps the arrowheads into a step with many arrows apart, and the arrows out of a wide split on its tile', async () => {
        const { layout, sizes, edges } = await layOut(busyJoin, computePathGroups(busyJoin), [])
        const xs = (from: VisibleEdge[], end: 0 | -1): number[] =>
            from.map(({ id }) => layout.edges[id].points.at(end)?.x ?? 0).sort((a, b) => a - b)
        const ends = xs(
            edges.filter((edge) => edge.target === 'exit'),
            -1
        )
        const gaps = ends.slice(1).map((x, index) => x - ends[index])
        const tile = sizes.split.anchor as Box
        const tileLeft = layout.positions.split.x + tile.x - tile.width / 2
        const starts = xs(
            edges.filter((edge) => edge.source === 'split'),
            0
        )

        expect(ends).toHaveLength(10)
        expect(Math.min(...gaps)).toBeGreaterThanOrEqual(8)
        expect(starts.filter((x) => x < tileLeft || x > tileLeft + tile.width)).toEqual([])
    })

    it('stops a layout that a newer one replaced before its next pass', async () => {
        const replaced = new Error('replaced')
        const stopIfStale = jest.fn(() => {
            throw replaced
        })

        await expect(layOut(workflow, groups, [], stopIfStale)).rejects.toBe(replaced)
        expect(stopIfStale).toHaveBeenCalledTimes(1)
    })

    it('gives a path no more room for a name longer than its label shows', () => {
        const named = (label: string): number =>
            pathFrameSpecs([{ ...outerArms[0], label }], [outerArms[0].id], [])[0].minWidth

        expect(named('Eligible and reachable, '.repeat(6))).toEqual(named('x'.repeat(40)))
    })
})
