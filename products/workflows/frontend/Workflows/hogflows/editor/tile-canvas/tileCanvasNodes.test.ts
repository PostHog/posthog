import { getEdgeId } from '../../edgeId'
import type { HogFlow, HogFlowAction, HogFlowEdge } from '../../types'
import { CanvasLayout } from './tileCanvasLayout'
import { computeVisibleGraph, MOVING_STEP_ATTR, Point, QUICK_ADD_ATTR, STEP_DRAG_DATA_TYPE } from './tileCanvasModel'
import {
    buildCanvasEdges,
    buildCanvasNodes,
    CanvasNodeState,
    handleStepDragOver,
    handleStepDrop,
    keepUnchangedNodes,
    nearestInsertEdge,
    StepDragEvent,
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

        describe('step drops on the canvas', () => {
            const aToB = getEdgeId({ from: 'a', to: 'b', type: 'continue' } as HogFlow['edges'][0])

            type DropTarget = 'pane' | 'plus' | 'moving step' | 'canvas panel'

            const releasedOver = (over: DropTarget): Element => {
                const holder = document.createElement('div')
                if (over === 'plus') {
                    holder.setAttribute('data-attr', QUICK_ADD_ATTR)
                } else if (over === 'moving step') {
                    holder.setAttribute(MOVING_STEP_ATTR, '')
                } else if (over === 'canvas panel') {
                    holder.className = 'react-flow__panel'
                }
                return holder.appendChild(document.createElement('span'))
            }

            const dragAt = (point: Point, types: string[], over: DropTarget): StepDragEvent => {
                return {
                    clientX: point.x,
                    clientY: point.y,
                    target: releasedOver(over),
                    dataTransfer: { types, dropEffect: 'none' },
                    preventDefault: jest.fn(),
                }
            }

            it.each([
                {
                    name: 'snaps a step dropped far from every + to the nearest +',
                    types: [STEP_DRAG_DATA_TYPE],
                    point: { x: 4000, y: 3000 },
                    expected: { highlights: [bToC, null], drops: [{ to: 'c', snapped: true }] },
                },
                {
                    name: 'keeps a drop on the + itself direct',
                    types: [STEP_DRAG_DATA_TYPE],
                    point: { x: 0, y: 50 },
                    over: 'plus' as const,
                    expected: { highlights: [aToB, null], drops: [{ to: 'b', snapped: false }] },
                },
                {
                    name: 'cancels a move let go on the moving step itself',
                    types: [STEP_DRAG_DATA_TYPE],
                    point: { x: 0, y: 150 },
                    over: 'moving step' as const,
                    expected: { highlights: [null], drops: [] },
                },
                {
                    name: 'cancels a drag let go over the controls on the canvas',
                    types: [STEP_DRAG_DATA_TYPE],
                    point: { x: 0, y: 150 },
                    over: 'canvas panel' as const,
                    expected: { highlights: [null], drops: [] },
                },
                {
                    name: 'refuses a step that no + can take',
                    types: [STEP_DRAG_DATA_TYPE],
                    point: { x: 0, y: 50 },
                    placeableEdgeKeys: new Set<string>(),
                    expected: { highlights: [null], drops: [] },
                },
                {
                    name: 'ignores a text drag while a step waits to be placed',
                    types: ['text/plain'],
                    point: { x: 0, y: 50 },
                    expected: { highlights: [], drops: [] },
                },
                {
                    name: 'ignores a step drag when the canvas waits for no step',
                    types: [STEP_DRAG_DATA_TYPE],
                    point: { x: 0, y: 50 },
                    isWaitingForStep: false,
                    expected: { highlights: [], drops: [] },
                },
            ])(
                '$name',
                ({
                    types,
                    point,
                    over: target = 'pane' as DropTarget,
                    placeableEdgeKeys = null,
                    isWaitingForStep = true,
                    expected,
                }) => {
                    const setDropTargetEdgeKey = jest.fn()
                    const dropAt = jest.fn<void, [HogFlowEdge, boolean]>()
                    const canvas = {
                        edges,
                        placeableEdgeKeys,
                        isWaitingForStep,
                        toFlowPoint: (screenPoint: Point) => screenPoint,
                        dropTargetEdgeKey: null,
                        setDropTargetEdgeKey,
                        dropAt,
                    }
                    const over = dragAt(point, types, target)

                    handleStepDragOver(over, canvas)
                    handleStepDrop(dragAt(point, types, target), canvas)

                    const accepted = expected.drops.length > 0
                    expect(over.preventDefault).toHaveBeenCalledTimes(accepted ? 1 : 0)
                    expect(over.dataTransfer.dropEffect).toBe(accepted ? 'move' : 'none')
                    expect(setDropTargetEdgeKey.mock.calls.map(([key]) => key)).toEqual(expected.highlights)
                    expect(dropAt.mock.calls.map(([edge, snapped]) => ({ to: edge.to, snapped }))).toEqual(
                        expected.drops
                    )
                }
            )
        })
    })
})
