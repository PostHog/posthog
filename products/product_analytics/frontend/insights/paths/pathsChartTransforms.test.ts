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

    it.each([
        { pinStepsUpTo: 3, columns: [0, 2, 1], stepsPinned: true },
        { pinStepsUpTo: 2, columns: [undefined, undefined, undefined], stepsPinned: false },
    ])(
        'pins nodes to their steps only within $pinStepsUpTo steps, labels URLs by path on a single origin, and keeps event names whole',
        ({ pinStepsUpTo, columns, stepsPinned }) => {
            const graph = buildPathsSankeyGraph(
                [
                    { source: '1_https://example.com/home', target: '3_https://example.com/#/app/settings', value: 4 },
                    { source: '1_https://example.com/home', target: '2_clicked: signup button', value: 2 },
                ],
                { labelUrls: true, pinStepsUpTo }
            )
            expect(graph.nodes.map(({ label }) => label)).toEqual([
                '/home',
                '/#/app/settings',
                'clicked: signup button',
            ])
            expect(graph.nodes.map(({ column }) => column)).toEqual(columns)
            expect(graph).toMatchObject({ stepCount: 3, stepsPinned })
        }
    )
})
