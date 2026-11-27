import { estimateCost } from './checkCosts'

describe('estimateCost', () => {
    const costs = {
        a: { median: 0.1, p90: 0.2 },
        b: { median: 0.05, p90: null },
    }

    it.each([
        ['a daily engine runs 30 times a month', [{ engine: 'a', frequency: 'daily' as const }], 1, 2, 30, 60],
        [
            'a weekly engine runs 52 / 12 times a month',
            [{ engine: 'a', frequency: 'weekly' as const }],
            1,
            2,
            4.33,
            8.67,
        ],
        [
            'an engine every 72 hours runs 10 times a month',
            [{ engine: 'a', frequency: 'every_3_days' as const }],
            1,
            2,
            10,
            20,
        ],
        [
            'an engine without a 90th percentile has no range',
            [{ engine: 'b', frequency: 'daily' as const }],
            0.5,
            0.5,
            15,
            15,
        ],
    ])('%s', (_name, engines, runLow, runHigh, monthLow, monthHigh) => {
        const estimate = estimateCost(10, engines, costs)

        expect(estimate.perRun.low).toBeCloseTo(runLow)
        expect(estimate.perRun.high).toBeCloseTo(runHigh)
        expect(estimate.perMonth.low).toBeCloseTo(monthLow, 1)
        expect(estimate.perMonth.high).toBeCloseTo(monthHigh, 1)
    })

    it('counts every engine in the checks but leaves an unpriced one out of the cost', () => {
        const estimate = estimateCost(
            10,
            [
                { engine: 'a', frequency: 'daily' },
                { engine: 'unknown', frequency: 'daily' },
            ],
            costs
        )

        expect(estimate.checksPerRun).toBe(20)
        expect(estimate.perRun).toEqual({ low: 1, high: 2 })
        expect(estimate.unpriced).toEqual(['unknown'])
    })
})
