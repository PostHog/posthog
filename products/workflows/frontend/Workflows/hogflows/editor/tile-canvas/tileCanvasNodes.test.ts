import { getEdgeId } from '../../edgeId'
import type { HogFlow, HogFlowAction } from '../../types'
import { CanvasLayout } from './tileCanvasLayout'
import { computeVisibleGraph } from './tileCanvasModel'
import {
    buildCanvasEdges,
    buildCanvasNodes,
    CanvasNodeState,
    keepUnchangedNodes,
    nearestInsertEdge,
} from './tileCanvasNodes'

const step = (id: string): HogFlowAction => ({ id, type: 'delay', name: id, config: {} }) as unknown as HogFlowAction

const workflow = {
    actions: [step('a'), step('b')],
    edges: [{ from: 'a', to: 'b', type: 'continue' }],
} as unknown as HogFlow

const graph = computeVisibleGraph(workflow, [], [])

const layoutWith = (bY: number): CanvasLayout => ({
    positions: { a: { x: 0, y: 0 }, b: { x: 0, y: bY } },
    edges: {},
    frames: {},
    width: 300,
    height: 300,
})

const state: CanvasNodeState = {
    workflow,
    groups: [],
    motion: null,
    sizes: null,
    selectedStepId: null,
    menuStepId: null,
    countOf: () => undefined,
    templateNameOf: () => undefined,
}

describe('tileCanvasNodes', () => {
    describe('keepUnchangedNodes', () => {
        it('keeps the node objects that did not change, so React Flow redraws only the rest', () => {
            const before = buildCanvasNodes(layoutWith(120), [], graph, state)

            const after = keepUnchangedNodes(
                before,
                buildCanvasNodes(layoutWith(200), [], graph, { ...state, selectedStepId: 'a' })
            )
            const moved = keepUnchangedNodes(before, buildCanvasNodes(layoutWith(200), [], graph, state))

            expect(after.map((node, index) => node === before[index])).toEqual([false, false])
            expect(moved.map((node, index) => node === before[index])).toEqual([true, false])
        })

        it('tells React Flow the size of each tile, so a replaced tile stays visible', () => {
            const sizes = { a: { width: 306, height: 84 }, b: { width: 306, height: 120 } }

            const nodes = buildCanvasNodes(layoutWith(120), [], graph, { ...state, sizes })

            expect(nodes.map((node) => node.measured)).toEqual([
                { width: 306, height: 84 },
                { width: 306, height: 120 },
            ])
        })
    })

    describe('nearestInsertEdge', () => {
        // a -> b -> c, with the + of a -> b near y 50 and the + of b -> c near y 250
        const chain = {
            actions: [step('a'), step('b'), step('c')],
            edges: [
                { from: 'a', to: 'b', type: 'continue' },
                { from: 'b', to: 'c', type: 'continue' },
            ],
        } as unknown as HogFlow
        const chainGraph = computeVisibleGraph(chain, [], [])
        const edges = buildCanvasEdges(chainGraph, {
            positions: {},
            edges: Object.fromEntries(
                chainGraph.edges.map((edge, index) => [
                    edge.id,
                    {
                        points: [
                            { x: 0, y: index * 200 },
                            { x: 0, y: index * 200 + 100 },
                        ],
                    },
                ])
            ),
            frames: {},
            width: 300,
            height: 600,
        })
        const bToC = getEdgeId({ from: 'b', to: 'c', type: 'continue' } as HogFlow['edges'][0])

        it.each([
            ['the closest + when no set is given', { x: 0, y: 50 }, null, 'b'],
            ['a + from the set, so a hidden + never takes the drop', { x: 0, y: 50 }, new Set([bToC]), 'c'],
            ['the closest + for a drop far from every +', { x: 4000, y: 3000 }, null, 'c'],
        ])('picks %s', (_, point, placeableEdgeKeys, expectedTo) => {
            expect(nearestInsertEdge(edges, point, placeableEdgeKeys)?.to).toBe(expectedTo)
        })

        it('finds no + when none can take the step', () => {
            expect(nearestInsertEdge(edges, { x: 0, y: 50 }, new Set())).toBeNull()
        })
    })
})
