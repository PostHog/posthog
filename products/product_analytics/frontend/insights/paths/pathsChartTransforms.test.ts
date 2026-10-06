import { buildPathsSankeyGraph, pathStartCount } from './pathsChartTransforms'

describe('pathsChartTransforms', () => {
    it('counts path starts from step 1 only, even when a later step has lost its incoming edge', () => {
        // A truncated result can keep `2_/pricing -> 3_/signup` without the edge into `2_/pricing`.
        const edges = [
            { source: '1_/home', target: '2_/docs', value: 10 },
            { source: '2_/pricing', target: '3_/signup', value: 12 },
        ]
        expect(pathStartCount(edges)).toBe(10)
    })

    it('pins each node to its step, labels URLs by path on a single origin, and keeps event names whole', () => {
        const graph = buildPathsSankeyGraph(
            [
                { source: '1_https://example.com/home', target: '3_https://example.com/#/app/settings', value: 4 },
                { source: '1_https://example.com/home', target: '2_clicked: signup button', value: 2 },
            ],
            { labelUrls: true, pinSteps: true }
        )
        expect(graph.nodes.map(({ label, column }) => [label, column])).toEqual([
            ['/home', 0],
            ['/#/app/settings', 2],
            ['clicked: signup button', 1],
        ])
        expect(graph.stepCount).toBe(3)
    })
})
