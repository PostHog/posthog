import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { InsightLogicProps } from '~/types'

import { pathsInteractionLogic } from './pathsInteractionLogic'
import { PathNodeData, PathTargetLink } from './pathUtils'

function buildTestNodes(): PathNodeData[] {
    const nodes: PathNodeData[] = [
        { name: '1_/', index: 0, layer: 0, y0: 0, y1: 100, depth: 0, value: 100 },
        { name: '2_/about', index: 1, layer: 1, y0: 0, y1: 80, depth: 1, value: 80 },
        { name: '3_/pricing', index: 2, layer: 2, y0: 0, y1: 60, depth: 2, value: 60 },
        { name: '3_/signup', index: 3, layer: 2, y0: 100, y1: 120, depth: 2, value: 20 },
    ].map((n) => ({
        ...n,
        targetLinks: [] as PathTargetLink[],
        sourceLinks: [] as PathTargetLink[],
        width: 15,
        height: n.y1 - n.y0,
        x0: n.layer * 200,
        x1: n.layer * 200 + 15,
        source: undefined as any,
        target: undefined as any,
    }))

    const links: PathTargetLink[] = [
        { index: 0, source: nodes[0], target: nodes[1], value: 80, width: 5, y0: 0, average_conversion_time: 1000 },
        { index: 1, source: nodes[1], target: nodes[2], value: 60, width: 4, y0: 0, average_conversion_time: 1000 },
        { index: 2, source: nodes[1], target: nodes[3], value: 20, width: 2, y0: 0, average_conversion_time: 500 },
    ].map((l) => ({ ...l, color: { r: 0, g: 0, b: 0 } }) as PathTargetLink)

    nodes[0].sourceLinks = [links[0]]
    nodes[1].targetLinks = [links[0]]
    nodes[1].sourceLinks = [links[1], links[2]]
    nodes[2].targetLinks = [links[1]]
    nodes[3].targetLinks = [links[2]]

    return nodes
}

const insightProps: InsightLogicProps = { dashboardItemId: undefined }

describe('pathsInteractionLogic', () => {
    let logic: ReturnType<typeof pathsInteractionLogic.build>

    beforeEach(() => {
        initKeaTests(false)
        logic = pathsInteractionLogic(insightProps)
        logic.mount()
    })

    it('starts with empty state', () => {
        expect(logic.values.nodes).toEqual([])
        expect(logic.values.hoverTarget).toBeNull()
        expect(logic.values.cardHovered).toBe(false)
        expect(logic.values.activeIndices.nodeIndices.size).toBe(0)
        expect(logic.values.resolvedNodeCards).toEqual([])
    })

    describe('setNodes', () => {
        it('stores nodes and canvas height', () => {
            const nodes = buildTestNodes()
            logic.actions.setNodes(nodes, 720)

            expect(logic.values.nodes).toEqual(nodes)
            expect(logic.values.canvasHeight).toBe(720)
        })

        it('clears any active hover target', () => {
            const nodes = buildTestNodes()
            logic.actions.setNodes(nodes, 720)
            logic.actions.hoverNode(0)

            expect(logic.values.hoverTarget).not.toBeNull()

            logic.actions.setNodes(nodes, 720)

            expect(logic.values.hoverTarget).toBeNull()
        })
    })

    describe('hoverNode — forward chain plus direct incoming links', () => {
        it.each([
            {
                scenario: 'hovering root highlights all downstream nodes and links',
                nodeIndex: 0,
                expectedNodes: [0, 1, 2, 3],
                expectedLinks: [0, 1, 2],
            },
            {
                scenario: 'hovering middle node includes incoming link and source plus forward',
                nodeIndex: 1,
                expectedNodes: [0, 1, 2, 3],
                expectedLinks: [0, 1, 2],
            },
            {
                scenario: 'hovering leaf includes its incoming link and source',
                nodeIndex: 2,
                expectedNodes: [1, 2],
                expectedLinks: [1],
            },
        ])('$scenario', ({ nodeIndex, expectedNodes, expectedLinks }) => {
            logic.actions.setNodes(buildTestNodes(), 720)
            logic.actions.hoverNode(nodeIndex)

            const { nodeIndices, linkIndices } = logic.values.activeIndices
            expect([...nodeIndices].sort()).toEqual(expectedNodes)
            expect([...linkIndices].sort()).toEqual(expectedLinks)
        })
    })

    describe('hoverLink — source + forward from target', () => {
        it('highlights source, the hovered link, target, and everything forward from target', () => {
            logic.actions.setNodes(buildTestNodes(), 720)
            // Hover link 0: / → /about
            logic.actions.hoverLink(0, 1, 0)

            const { nodeIndices, linkIndices } = logic.values.activeIndices
            // Source (/) + target (/about) + forward from /about (/pricing, /signup)
            expect([...nodeIndices].sort()).toEqual([0, 1, 2, 3])
            // Hovered link (0) + forward links from /about (1, 2)
            expect([...linkIndices].sort()).toEqual([0, 1, 2])
        })

        it('hovering the last link highlights only source, link, and target', () => {
            logic.actions.setNodes(buildTestNodes(), 720)
            // Hover link 1: /about → /pricing (leaf)
            logic.actions.hoverLink(1, 2, 1)

            const { nodeIndices, linkIndices } = logic.values.activeIndices
            expect([...nodeIndices].sort()).toEqual([1, 2])
            expect([...linkIndices].sort()).toEqual([1])
        })
    })

    describe('clearHover', () => {
        it('resets hover target and active indices', async () => {
            logic.actions.setNodes(buildTestNodes(), 720)
            logic.actions.hoverNode(0)

            expect(logic.values.activeIndices.nodeIndices.size).toBeGreaterThan(0)

            logic.actions.clearHover()

            await expectLogic(logic).toMatchValues({
                hoverTarget: null,
            })
            expect(logic.values.activeIndices.nodeIndices.size).toBe(0)
        })
    })

    describe('cardHovered', () => {
        it('tracks card hover state independently', () => {
            logic.actions.setCardHovered(true)
            expect(logic.values.cardHovered).toBe(true)

            logic.actions.setCardHovered(false)
            expect(logic.values.cardHovered).toBe(false)
        })

        it('is reset by clearHover', () => {
            logic.actions.setCardHovered(true)
            logic.actions.clearHover()
            expect(logic.values.cardHovered).toBe(false)
        })
    })

    describe('resolvedNodeCards', () => {
        it('marks active nodes as visible and active', () => {
            const nodes = buildTestNodes()
            // Make node 3 short enough to be hidden by default
            nodes[3] = { ...nodes[3], y0: 100, y1: 110 }
            logic.actions.setNodes(nodes, 720)

            // Before hover: node 3 should be hidden (height 10 < 30)
            const beforeCards = logic.values.resolvedNodeCards
            expect(beforeCards.find((n) => n.index === 3)?.visible).toBe(false)

            // Hover middle node: node 3 is in the forward chain
            logic.actions.hoverNode(1)

            const afterCards = logic.values.resolvedNodeCards
            expect(afterCards.find((n) => n.index === 3)?.visible).toBe(true)
            expect(afterCards.find((n) => n.index === 3)?.active).toBe(true)
        })

        it('deactivates all nodes when hover is cleared', () => {
            logic.actions.setNodes(buildTestNodes(), 720)
            logic.actions.hoverNode(0)
            logic.actions.clearHover()

            const cards = logic.values.resolvedNodeCards
            expect(cards.every((n) => n.active === false)).toBe(true)
        })
    })
})
