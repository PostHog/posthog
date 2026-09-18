import { RGBColor } from 'd3'

import {
    PathNodeData,
    PathTargetLink,
    activateNodes,
    deactivateNodes,
    getForwardConnectedIndices,
    pageUrl,
    resolveCardOverlaps,
} from './pathUtils'

/**
 * Builds a linear path graph: A → B → C → ...
 * with an optional branch at any node.
 *
 *   buildPathGraph(['/', '/about', '/pricing'])
 *
 * produces three nodes with links 0→1 and 1→2.
 *
 *   buildPathGraph(['/', '/about', '/pricing'], { branchAt: 1, branchTargets: ['/signup'] })
 *
 * adds a branch from /about → /signup (node index 3, link index 2).
 */
function buildPathGraph(
    names: string[],
    opts?: { branchAt: number; branchTargets: string[] }
): { nodes: PathNodeData[]; links: PathTargetLink[] } {
    const nodes: PathNodeData[] = names.map((name, i) => ({
        name: `${i + 1}_${name}`,
        targetLinks: [],
        sourceLinks: [],
        depth: i,
        width: 15,
        height: 100,
        index: i,
        value: 100 - i * 10,
        x0: i * 200,
        x1: i * 200 + 15,
        y0: 0,
        y1: 100,
        layer: i,
        source: undefined as any,
        target: undefined as any,
    }))

    const links: PathTargetLink[] = []
    let linkIndex = 0

    for (let i = 0; i < nodes.length - 1; i++) {
        const link: PathTargetLink = {
            average_conversion_time: 1000,
            index: linkIndex++,
            source: nodes[i],
            target: nodes[i + 1],
            value: nodes[i + 1].value,
            width: 5,
            y0: 0,
            color: { r: 0, g: 0, b: 0 } as RGBColor,
        }
        nodes[i].sourceLinks.push(link)
        nodes[i + 1].targetLinks.push(link)
        links.push(link)
    }

    if (opts) {
        const branchSource = nodes[opts.branchAt]
        for (const branchName of opts.branchTargets) {
            const branchNode: PathNodeData = {
                name: `${nodes.length + 1}_${branchName}`,
                targetLinks: [],
                sourceLinks: [],
                depth: branchSource.depth + 1,
                width: 15,
                height: 50,
                index: nodes.length,
                value: 20,
                x0: (branchSource.depth + 1) * 200,
                x1: (branchSource.depth + 1) * 200 + 15,
                y0: 200,
                y1: 250,
                layer: branchSource.layer + 1,
                source: undefined as any,
                target: undefined as any,
            }
            const branchLink: PathTargetLink = {
                average_conversion_time: 500,
                index: linkIndex++,
                source: branchSource,
                target: branchNode,
                value: 20,
                width: 3,
                y0: 0,
                color: { r: 0, g: 0, b: 0 } as RGBColor,
            }
            branchSource.sourceLinks.push(branchLink)
            branchNode.targetLinks.push(branchLink)
            nodes.push(branchNode)
            links.push(branchLink)
        }
    }

    return { nodes, links }
}

describe('pageUrl', () => {
    it('should correctly process PathNodeData with hash based URL', () => {
        const testData = {
            name: '2_https://example.com/#/auth/login',
            targetLinks: [
                {
                    average_conversion_time: 0,
                    index: 0,
                    value: 0,
                    width: 0,
                    y0: 0,
                    color: { r: 0, g: 0, b: 0 } as RGBColor,
                    target: {
                        name: '1_https://example.com/',
                        targetLinks: [],
                        sourceLinks: [],
                        depth: 0,
                        width: 0,
                        height: 0,
                        index: 0,
                        value: 0,
                        x0: 0,
                        x1: 0,
                        y0: 0,
                        y1: 0,
                        layer: 0,
                        visible: true,
                    },
                    source: {
                        name: '1_https://example.com/',
                        targetLinks: [],
                        sourceLinks: [],
                        depth: 0,
                        width: 0,
                        height: 0,
                        index: 0,
                        value: 0,
                        x0: 0,
                        x1: 0,
                        y0: 0,
                        y1: 0,
                        layer: 0,
                        visible: true,
                    },
                },
            ],
            sourceLinks: [],
            depth: 0,
            width: 0,
            height: 0,
            index: 0,
            value: 0,
            x0: 0,
            x1: 0,
            y0: 0,
            y1: 0,
            layer: 0,
            visible: true,
        } as unknown as PathNodeData

        const result = pageUrl(testData, true)
        expect(result).toBe('/#/auth/login')
    })

    it('should correctly process PathNodeData with unrelated hash in URL', () => {
        const testData = {
            name: '2_https://example.com/auth/login#sidepanel=explore',
            targetLinks: [
                {
                    average_conversion_time: 0,
                    index: 0,
                    value: 0,
                    width: 0,
                    y0: 0,
                    color: { r: 0, g: 0, b: 0 } as RGBColor,
                    target: {
                        name: '1_https://example.com/',
                        targetLinks: [],
                        sourceLinks: [],
                        depth: 0,
                        width: 0,
                        height: 0,
                        index: 0,
                        value: 0,
                        x0: 0,
                        x1: 0,
                        y0: 0,
                        y1: 0,
                        layer: 0,
                        visible: true,
                    },
                    source: {
                        name: '1_https://example.com/',
                        targetLinks: [],
                        sourceLinks: [],
                        depth: 0,
                        width: 0,
                        height: 0,
                        index: 0,
                        value: 0,
                        x0: 0,
                        x1: 0,
                        y0: 0,
                        y1: 0,
                        layer: 0,
                        visible: true,
                    },
                },
            ],
            sourceLinks: [],
            depth: 0,
            width: 0,
            height: 0,
            index: 0,
            value: 0,
            x0: 0,
            x1: 0,
            y0: 0,
            y1: 0,
            layer: 0,
            visible: true,
        } as unknown as PathNodeData

        const result = pageUrl(testData, true)
        expect(result).toBe('/auth/login')
    })

    it('should correctly process PathNodeData with regular URL', () => {
        const testData = {
            name: '2_https://example.com/path',
            targetLinks: [
                {
                    average_conversion_time: 0,
                    index: 0,
                    value: 0,
                    width: 0,
                    y0: 0,
                    color: { r: 0, g: 0, b: 0 } as RGBColor,
                    target: {
                        name: '1_https://example.com/',
                        targetLinks: [],
                        sourceLinks: [],
                        depth: 0,
                        width: 0,
                        height: 0,
                        index: 0,
                        value: 0,
                        x0: 0,
                        x1: 0,
                        y0: 0,
                        y1: 0,
                        layer: 0,
                        visible: true,
                    },
                    source: {
                        name: '1_https://example.com/',
                        targetLinks: [],
                        sourceLinks: [],
                        depth: 0,
                        width: 0,
                        height: 0,
                        index: 0,
                        value: 0,
                        x0: 0,
                        x1: 0,
                        y0: 0,
                        y1: 0,
                        layer: 0,
                        visible: true,
                    },
                },
            ],
            sourceLinks: [],
            depth: 0,
            width: 0,
            height: 0,
            index: 0,
            value: 0,
            x0: 0,
            x1: 0,
            y0: 0,
            y1: 0,
            layer: 0,
            visible: true,
        } as unknown as PathNodeData

        const result = pageUrl(testData, true)
        expect(result).toBe('/path')
    })

    it('should decode URL-encoded characters in path cleaning aliases', () => {
        const testData = {
            name: '2_https://example.com/files/<id>',
            targetLinks: [
                {
                    average_conversion_time: 0,
                    index: 0,
                    value: 0,
                    width: 0,
                    y0: 0,
                    color: { r: 0, g: 0, b: 0 } as RGBColor,
                    target: {
                        name: '1_https://example.com/',
                        targetLinks: [],
                        sourceLinks: [],
                        depth: 0,
                        width: 0,
                        height: 0,
                        index: 0,
                        value: 0,
                        x0: 0,
                        x1: 0,
                        y0: 0,
                        y1: 0,
                        layer: 0,
                        visible: true,
                    },
                    source: {
                        name: '1_https://example.com/',
                        targetLinks: [],
                        sourceLinks: [],
                        depth: 0,
                        width: 0,
                        height: 0,
                        index: 0,
                        value: 0,
                        x0: 0,
                        x1: 0,
                        y0: 0,
                        y1: 0,
                        layer: 0,
                        visible: true,
                    },
                },
            ],
            sourceLinks: [],
            depth: 0,
            width: 0,
            height: 0,
            index: 0,
            value: 0,
            x0: 0,
            x1: 0,
            y0: 0,
            y1: 0,
            layer: 0,
            visible: true,
        } as unknown as PathNodeData

        // The URL API encodes < and > to %3C and %3E, but we should decode them back
        const result = pageUrl(testData, true)
        expect(result).toBe('/files/<id>')
    })
})

describe('getForwardConnectedIndices', () => {
    // Graph:  A(0) → B(1) → C(2)
    //                  ↘ D(3)
    it.each([
        {
            scenario: 'from root node includes all downstream nodes and links',
            startIndex: 0,
            expectedNodes: [0, 1, 2, 3],
            expectedLinks: [0, 1, 2],
        },
        {
            scenario: 'from middle node includes only forward nodes',
            startIndex: 1,
            expectedNodes: [1, 2, 3],
            expectedLinks: [1, 2],
        },
        {
            scenario: 'from leaf node includes only itself',
            startIndex: 2,
            expectedNodes: [2],
            expectedLinks: [],
        },
        {
            scenario: 'from branch leaf includes only itself',
            startIndex: 3,
            expectedNodes: [3],
            expectedLinks: [],
        },
    ])('$scenario', ({ startIndex, expectedNodes, expectedLinks }) => {
        const { nodes } = buildPathGraph(['/', '/about', '/pricing'], {
            branchAt: 1,
            branchTargets: ['/signup'],
        })

        const { nodeIndices, linkIndices } = getForwardConnectedIndices(nodes[startIndex])

        expect([...nodeIndices].sort()).toEqual(expectedNodes)
        expect([...linkIndices].sort()).toEqual(expectedLinks)
    })

    it('does not trace backward from a node', () => {
        const { nodes } = buildPathGraph(['/', '/about', '/pricing'])
        const endNode = nodes[2]

        const { nodeIndices, linkIndices } = getForwardConnectedIndices(endNode)

        expect([...nodeIndices]).toEqual([2])
        expect([...linkIndices]).toEqual([])
    })
})

describe('activateNodes', () => {
    it('sets active and visible on matching indices, preserves height-based visibility for others', () => {
        const { nodes } = buildPathGraph(['/', '/about', '/pricing'])
        // Make node 2 short enough to be hidden by default
        nodes[2] = { ...nodes[2], y0: 0, y1: 10 }

        const activeIndices = new Set([0, 2])
        const result = activateNodes(nodes, activeIndices)

        expect(result[0].active).toBe(true)
        expect(result[0].visible).toBe(true)
        expect(result[1].active).toBe(false)
        expect(result[1].visible).toBe(true) // tall enough (y1-y0 = 100 > 30)
        expect(result[2].active).toBe(true)
        expect(result[2].visible).toBe(true) // active overrides height check
    })
})

describe('deactivateNodes', () => {
    it('resets active to false and sets visibility by height threshold', () => {
        const { nodes } = buildPathGraph(['/', '/about'])
        nodes[0] = { ...nodes[0], y0: 0, y1: 100, active: true, visible: true }
        nodes[1] = { ...nodes[1], y0: 0, y1: 10, active: true, visible: true }

        const result = deactivateNodes(nodes)

        expect(result[0].active).toBe(false)
        expect(result[0].visible).toBe(true) // 100 > 30
        expect(result[1].active).toBe(false)
        expect(result[1].visible).toBe(false) // 10 < 30
    })
})

describe('resolveCardOverlaps', () => {
    it('nudges overlapping cards in the same layer apart', () => {
        const { nodes } = buildPathGraph(['/', '/about'])
        // Two nodes in different layers — won't overlap each other
        // Override to put them in the same layer with close y positions
        nodes[0] = { ...nodes[0], layer: 0, y0: 0, y1: 100, visible: true }
        nodes[1] = { ...nodes[1], layer: 0, y0: 5, y1: 105, visible: true }

        const result = resolveCardOverlaps(nodes, 720)

        expect(result[0].resolvedTop).not.toBeUndefined()
        expect(result[1].resolvedTop).not.toBeUndefined()
        expect(result[1].resolvedTop!).toBeGreaterThan(result[0].resolvedTop!)
        // Gap should be at least CARD_HEIGHT + OVERLAP_GAP
        expect(result[1].resolvedTop! - result[0].resolvedTop!).toBeGreaterThanOrEqual(42) // 38 + 4
    })

    it('does not adjust cards in different layers', () => {
        const { nodes } = buildPathGraph(['/', '/about'])
        nodes[0] = { ...nodes[0], layer: 0, y0: 0, y1: 100, visible: true }
        nodes[1] = { ...nodes[1], layer: 1, y0: 5, y1: 105, visible: true }

        const result = resolveCardOverlaps(nodes, 720)

        // Each card gets its own layer group — no nudging needed
        expect(result[0].resolvedTop).not.toBeUndefined()
        expect(result[1].resolvedTop).not.toBeUndefined()
    })

    it('leaves hidden nodes without resolvedTop', () => {
        const { nodes } = buildPathGraph(['/', '/about'])
        nodes[0] = { ...nodes[0], visible: true }
        nodes[1] = { ...nodes[1], visible: false }

        const result = resolveCardOverlaps(nodes, 720)

        expect(result[0].resolvedTop).not.toBeUndefined()
        expect(result[1].resolvedTop).toBeUndefined()
    })
})
