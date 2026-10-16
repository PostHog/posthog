import type { SankeyChartLayout, SankeyLinkDatum, SankeyNodeDatum } from '@posthog/quill-charts'

import { PathsLink } from '~/queries/schema/schema-general'

import { buildPathsGraph, maxPathLayer, pathsChartWidth, toPathNodeData } from './pathsChartData'
import { Paths } from './types'

const COLORS = { node: '#111111', selectedNode: '#222222', link: '#333333' }

const LINKS: PathsLink[] = [
    { source: '1_/home', target: '2_/pricing', value: 30, average_conversion_time: 4000 },
    { source: '1_/home', target: '2_/docs', value: 10, average_conversion_time: 2000 },
    { source: '2_/pricing', target: '3_/signup', value: 12, average_conversion_time: 9000 },
]
const PATHS: Paths = {
    nodes: [{ name: '1_/home' }, { name: '2_/pricing' }, { name: '2_/docs' }, { name: '3_/signup' }],
    links: LINKS,
}

function layoutOf(paths: Paths): SankeyChartLayout<unknown, PathsLink> {
    const nodes = paths.nodes.map(
        (node, index): SankeyNodeDatum => ({
            id: node.name,
            label: node.name,
            color: '#000',
            index,
            column: Number(node.name.match(/[^_]*/)) - 1,
            value: 40,
            x0: index * 100,
            x1: index * 100 + 15,
            y0: 0,
            y1: 40,
        })
    )
    const byId = new Map(nodes.map((node) => [node.id, node]))
    const links = paths.links.map(
        (link, index): SankeyLinkDatum<unknown, PathsLink> => ({
            source: byId.get(link.source)!,
            target: byId.get(link.target)!,
            value: link.value,
            color: '#000',
            meta: link,
            index,
            y0: 0,
            y1: 0,
            width: link.value,
        })
    )
    return { nodes, links, columnCount: 3, columnX: [0, 100, 300], total: 40, nodeWidth: 15 }
}

describe('pathsChartData', () => {
    it('colors the selected start point and keeps the result link on each ribbon', () => {
        const graph = buildPathsGraph(PATHS, { startPoint: '/home' }, undefined, COLORS)
        expect(graph.nodes.map((n) => n.color)).toEqual(['#222222', '#111111', '#111111', '#111111'])
        // A selected start point that other steps lead into is not a path start, so no accent.
        const notAStart = buildPathsGraph(PATHS, { startPoint: '/pricing' }, undefined, COLORS)
        expect(notAStart.nodes[1].color).toBe('#111111')
        expect(graph.links[2].meta).toBe(LINKS[2])
    })

    it('rebuilds the node graph the hover logic walks, keyed by the chart indices', () => {
        const nodes = toPathNodeData(layoutOf(PATHS))
        const home = nodes.find((n) => n.name === '1_/home')!
        const signup = nodes.find((n) => n.name === '3_/signup')!
        expect(nodes.map((n) => n.index)).toEqual([0, 1, 2, 3])
        expect(home.sourceLinks.map((l) => [l.index, l.target.name])).toEqual([
            [0, '2_/pricing'],
            [1, '2_/docs'],
        ])
        expect(signup.targetLinks[0]).toMatchObject({ index: 2, average_conversion_time: 9000, value: 12 })
        expect(signup.targetLinks[0].source).toBe(nodes[1])
        expect([home.layer, signup.layer]).toEqual([0, 2])
    })

    it.each([
        [1200, 3, 1200],
        [600, 2, 600],
        [600, 3, 1000],
        [1000, 8, 1600],
    ])('sizes a %dpx container with %d steps to %dpx', (containerWidth, steps, expected) => {
        expect(pathsChartWidth(containerWidth, steps)).toBe(expected)
    })

    it('reads the step count from the link targets', () => {
        expect(maxPathLayer(PATHS)).toBe(3)
        expect(maxPathLayer({ nodes: [], links: [] })).toBe(0)
    })
})
