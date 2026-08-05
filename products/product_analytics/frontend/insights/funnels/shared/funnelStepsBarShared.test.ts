import {
    buildFunnelStepsBarConfig,
    buildFunnelStepsBars,
    buildSingleSeriesFunnelStepsBars,
    FUNNEL_STEPS_BAR_SERIES_KEY,
    type FunnelStepsBarVariant,
} from './funnelStepsBarShared'

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
        const steps = [
            { name: 'Pageview', count: 1000 },
            { name: 'Signed up', count: 400 },
            { name: 'Activated', count: 100 },
        ]
        const variants: FunnelStepsBarVariant[] = [{ key: 'a', label: 'A', color: '#1d4aff', data: [100, 40, 10] }]

        it('labels the band by 1-based step index, not the step name', () => {
            expect(buildFunnelStepsBars(steps, variants).labels).toEqual(['1', '2', '3'])
        })

        it('keeps duplicate-named steps on distinct bands so they do not collapse', () => {
            const dupSteps = [
                { name: '$pageview', count: 10 },
                { name: '$pageview', count: 2 },
            ]
            expect(buildFunnelStepsBars(dupSteps, variants).labels).toEqual(['1', '2'])
        })

        it('wraps each variant as a series, preserving key, color, data, and meta', () => {
            const { series } = buildFunnelStepsBars(steps, [
                { key: 'mobile', label: 'Mobile', color: '#f00', data: [100, 60], meta: { breakdownIndex: 0 } },
                { key: 'desktop', label: 'Desktop', color: '#0f0', data: [100, 30], meta: { breakdownIndex: 1 } },
            ])

            expect(series).toHaveLength(2)
            expect(series[0]).toMatchObject({ key: 'mobile', label: 'Mobile', color: '#f00', data: [100, 60] })
            expect(series.map((s) => s.meta?.breakdownIndex)).toEqual([0, 1])
        })

        it('computes per-step conversion vs the first step and vs the previous step from counts', () => {
            const { rows } = buildFunnelStepsBars(steps, variants)

            expect(rows.map((r) => r.fractionOfBasis)).toEqual([1, 0.4, 0.1])
            // step 0 has no previous step (value unused by the view); steps 1/2 are vs the prior count.
            expect(rows.map((r) => r.fromPrevious)).toEqual([0, 0.4, 0.25])
            expect(rows.map((r) => r.stepIndex)).toEqual([0, 1, 2])
            expect(rows.map((r) => r.count)).toEqual([1000, 400, 100])
        })

        it('reports overall conversion as last/first', () => {
            expect(buildFunnelStepsBars(steps, variants).overall).toEqual({
                rate: 0.1,
                firstCount: 1000,
                lastCount: 100,
            })
        })

        it('returns an empty model for an empty funnel', () => {
            expect(buildFunnelStepsBars([], [])).toEqual({
                series: [],
                labels: [],
                rows: [],
                overall: { rate: 0, firstCount: 0, lastCount: 0 },
            })
        })
    })

    describe('buildSingleSeriesFunnelStepsBars', () => {
        const OPTS = { color: '#1d4aff' }
        const steps = [
            { name: 'Pageview', count: 1000 },
            { name: 'Signed up', count: 400 },
            { name: 'Activated', count: 100 },
        ]

        it('derives one series of per-step conversion-from-first, as a percent', () => {
            const { series } = buildSingleSeriesFunnelStepsBars(steps, OPTS)

            expect(series).toHaveLength(1)
            expect(series[0]).toMatchObject({ key: FUNNEL_STEPS_BAR_SERIES_KEY, color: '#1d4aff', data: [100, 40, 10] })
        })

        it('guards divide-by-zero when the first step has no entries', () => {
            const { series, rows, overall } = buildSingleSeriesFunnelStepsBars(
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

        it('returns a single empty series for an empty funnel', () => {
            const { series, labels, rows, overall } = buildSingleSeriesFunnelStepsBars([], OPTS)

            expect(series[0].data).toEqual([])
            expect(labels).toEqual([])
            expect(rows).toEqual([])
            expect(overall).toEqual({ rate: 0, firstCount: 0, lastCount: 0 })
        })
    })
})
