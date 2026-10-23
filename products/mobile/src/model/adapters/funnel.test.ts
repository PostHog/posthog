import { funnelView } from './funnel'

function funnels(extra: Record<string, unknown> = {}): unknown {
    return { kind: 'InsightVizNode', source: { kind: 'FunnelsQuery', series: [], ...extra } }
}

function steps(counts: number[], breakdown?: string): Record<string, unknown>[] {
    return counts.map((count, order) => ({
        name: `step ${order}`,
        order,
        count,
        median_conversion_time: order > 0 ? 60 : null,
        ...(breakdown ? { breakdown_value: breakdown } : {}),
    }))
}

describe('funnelView', () => {
    test('adds the breakdown values up step by step', () => {
        const result = [steps([100, 40, 10], 'Chrome'), steps([50, 20, 5], 'Safari')]

        expect(funnelView(funnels({ breakdownFilter: { breakdown: '$browser' } }), result)).toMatchObject({
            breakdownValues: 2,
            conversion: 10,
            steps: [
                { count: 150, percentOfPrevious: null, droppedOff: null },
                { count: 60, percentOfFirst: 40, percentOfPrevious: 40, droppedOff: 90, medianSeconds: null },
                { count: 15, percentOfFirst: 10, percentOfPrevious: 25, droppedOff: 45, medianSeconds: null },
            ],
        })
    })

    test.each<[string, unknown]>([
        [
            'a cohort breakdown, which can count a person twice',
            funnels({ breakdownFilter: { breakdown: [3], breakdown_type: 'cohort' } }),
        ],
        ['the trends layout', funnels({ funnelsFilter: { funnelVizType: 'trends' } })],
    ])('leaves %s to the web', (_name, query) => {
        expect(funnelView(query, [steps([10, 5], 'a'), steps([8, 2], 'b')])).toBeNull()
    })
})
