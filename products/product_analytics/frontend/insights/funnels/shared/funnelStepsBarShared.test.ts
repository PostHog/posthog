import { buildFunnelStepsBarConfig, buildFunnelStepsBars, FUNNEL_STEPS_BAR_SERIES_KEY } from './funnelStepsBarShared'

describe('funnelStepsBarShared', () => {
    // The rest of buildFunnelStepsBarConfig is a declarative config literal; only the value-axis
    // formatter carries behavior worth pinning down.
    describe('buildFunnelStepsBarConfig value-axis formatter', () => {
        it.each([
            { value: 0, expected: '0%' },
            { value: 42.4, expected: '42%' },
            { value: 42.6, expected: '43%' },
            { value: 100, expected: '100%' },
        ])('rounds $value to $expected', ({ value, expected }) => {
            expect(buildFunnelStepsBarConfig().yTickFormatter?.(value)).toBe(expected)
        })
    })

    describe('buildFunnelStepsBars', () => {
        const OPTS = { color: '#1d4aff' }
        const steps = [
            { name: 'Pageview', count: 1000 },
            { name: 'Signed up', count: 400 },
            { name: 'Activated', count: 100 },
        ]

        it('emits one series of per-step conversion-from-first, as a percent', () => {
            const { series } = buildFunnelStepsBars(steps, OPTS)

            expect(series).toHaveLength(1)
            expect(series[0]).toMatchObject({ key: FUNNEL_STEPS_BAR_SERIES_KEY, color: '#1d4aff', data: [100, 40, 10] })
        })

        it('labels the axis with the step names', () => {
            expect(buildFunnelStepsBars(steps, OPTS).labels).toEqual(['Pageview', 'Signed up', 'Activated'])
        })

        it('computes per-step conversion vs the first step and vs the previous step', () => {
            const { rows } = buildFunnelStepsBars(steps, OPTS)

            expect(rows.map((r) => r.fractionOfBasis)).toEqual([1, 0.4, 0.1])
            // step 0 has no previous step (value unused by the view); steps 1/2 are vs the prior count.
            expect(rows.map((r) => r.fromPrevious)).toEqual([0, 0.4, 0.25])
            expect(rows.map((r) => r.stepIndex)).toEqual([0, 1, 2])
            expect(rows.map((r) => r.count)).toEqual([1000, 400, 100])
        })

        it('reports overall conversion as last/first', () => {
            expect(buildFunnelStepsBars(steps, OPTS).overall).toEqual({ rate: 0.1, firstCount: 1000, lastCount: 100 })
        })

        it('guards divide-by-zero when the first step has no entries', () => {
            const { series, rows, overall } = buildFunnelStepsBars(
                [
                    { name: 'A', count: 0 },
                    { name: 'B', count: 0 },
                ],
                OPTS
            )

            expect(series[0].data).toEqual([0, 0])
            expect(rows.map((r) => r.fractionOfBasis)).toEqual([0, 0])
            expect(overall.rate).toBe(0)
        })

        it('returns an empty model for an empty funnel', () => {
            const { series, labels, rows, overall } = buildFunnelStepsBars([], OPTS)

            expect(series[0].data).toEqual([])
            expect(labels).toEqual([])
            expect(rows).toEqual([])
            expect(overall).toEqual({ rate: 0, firstCount: 0, lastCount: 0 })
        })
    })
})
