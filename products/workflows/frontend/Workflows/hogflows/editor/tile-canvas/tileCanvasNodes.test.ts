import type { HogFlow, HogFlowAction } from '../../types'
import { CanvasLayout } from './tileCanvasLayout'
import { computeVisibleGraph } from './tileCanvasModel'
import { buildCanvasNodes, CanvasNodeState, keepUnchangedNodes } from './tileCanvasNodes'

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
