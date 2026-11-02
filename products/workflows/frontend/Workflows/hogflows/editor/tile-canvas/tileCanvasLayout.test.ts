import type { HogFlowAction, HogFlowEdge } from '../../types'
import { layoutTileCanvas, NodeSize, pathFrameSpecs } from './tileCanvasLayout'
import { computePathGroups, computeVisibleGraph, PathGroup } from './tileCanvasModel'

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

async function layoutWith(openIds: string[]): Promise<(group: PathGroup) => { x: number; top: number }> {
    const graph = computeVisibleGraph(workflow, groups, openIds)
    const sizes: Record<string, NodeSize> = Object.fromEntries(
        graph.nodes.map((node) => [
            node.id,
            node.kind === 'stack' ? { width: 180, height: 90 } : { width: 64, height: 64 },
        ])
    )
    const layout = await layoutTileCanvas(sizes, graph.edges, pathFrameSpecs(groups, openIds, graph.nodes))
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

    it('gives a path no more room for a name longer than its label shows', () => {
        const named = (label: string): number =>
            pathFrameSpecs([{ ...outerArms[0], label }], [outerArms[0].id], [])[0].minWidth

        expect(named('Eligible and reachable, '.repeat(6))).toEqual(named('x'.repeat(40)))
    })
})
