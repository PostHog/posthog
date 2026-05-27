// Static color stub so the test doesn't depend on the runtime CSS variable.
jest.mock('lib/colors', () => ({
    ...jest.requireActual('lib/colors'),
    getBarColorFromStatus: (status: string): string =>
        ({
            new: '#11ff11',
            resurrecting: '#22ff22',
            returning: '#33ff33',
            dormant: '#44ff44',
        })[status] ?? '#000000',
}))

import {
    buildTrendsLifecycleConfig,
    buildTrendsLifecycleSeries,
    shortenLifecycleLabel,
    type TrendsLifecycleResultLike,
} from './trendsLifecycleChartTransforms'

describe('buildTrendsLifecycleSeries', () => {
    it('orders series new → resurrecting → returning → dormant regardless of input order', () => {
        const results: TrendsLifecycleResultLike[] = [
            { id: 'dormant', status: 'dormant', label: 'Pageview - dormant', data: [-1, -2, -3] },
            { id: 'returning', status: 'returning', label: 'Pageview - returning', data: [1, 2, 3] },
            { id: 'new', status: 'new', label: 'Pageview - new', data: [1, 2, 3] },
            { id: 'resurrecting', status: 'resurrecting', label: 'Pageview - resurrecting', data: [1, 2, 3] },
        ]
        const series = buildTrendsLifecycleSeries(results)

        expect(series.map((s) => s.key)).toEqual(['new', 'resurrecting', 'returning', 'dormant'])
    })

    it('preserves dormant data as negative — diverging stack relies on the sign', () => {
        const series = buildTrendsLifecycleSeries([
            { id: 'dormant', status: 'dormant', label: 'Pageview - dormant', data: [-5, -6, -7] },
        ])

        expect(series[0].data).toEqual([-5, -6, -7])
    })

    it('uses fixed colors per lifecycle status, ignoring the data-color theme', () => {
        const results: TrendsLifecycleResultLike[] = [
            { id: 'new', status: 'new', label: 'Pageview - new', data: [1, 2, 3] },
            { id: 'resurrecting', status: 'resurrecting', label: 'Pageview - resurrecting', data: [1, 2, 3] },
            { id: 'returning', status: 'returning', label: 'Pageview - returning', data: [1, 2, 3] },
            { id: 'dormant', status: 'dormant', label: 'Pageview - dormant', data: [-1, -2, -3] },
        ]
        const series = buildTrendsLifecycleSeries(results)
        expect(series.map((s) => s.color)).toEqual(['#11ff11', '#22ff22', '#33ff33', '#44ff44'])
    })

    it('shortens series labels to capitalized status — used by both legend and tooltip', () => {
        const series = buildTrendsLifecycleSeries([
            { id: 'new', status: 'new', label: 'Pageview - new', data: [1] },
            { id: 'dormant', status: 'dormant', label: 'Pageview - dormant', data: [-1] },
        ])
        expect(series.find((s) => s.key === 'new')?.label).toBe('New')
        expect(series.find((s) => s.key === 'dormant')?.label).toBe('Dormant')
    })

    it('attaches meta from buildMeta with the original (pre-sort) index', () => {
        const results: TrendsLifecycleResultLike[] = [
            { id: 'dormant', status: 'dormant', label: 'Pageview - dormant', data: [-1] },
            { id: 'new', status: 'new', label: 'Pageview - new', data: [1] },
        ]
        const calls: Array<{ status: string; index: number }> = []
        buildTrendsLifecycleSeries(results, {
            buildMeta: (r, i) => {
                calls.push({ status: r.status!, index: i })
                return r.status
            },
        })
        // dormant was at original index 0, new at original index 1 — order is preserved in the callback.
        expect(calls).toEqual(
            expect.arrayContaining([
                { status: 'dormant', index: 0 },
                { status: 'new', index: 1 },
            ])
        )
    })

    it('marks excluded series with visibility.excluded so the chart skips them', () => {
        const results: TrendsLifecycleResultLike[] = [
            { id: 'new', status: 'new', label: 'Pageview - new', data: [1] },
            { id: 'dormant', status: 'dormant', label: 'Pageview - dormant', data: [-1] },
        ]
        const series = buildTrendsLifecycleSeries(results, {
            getHidden: (r) => r.status === 'dormant',
        })
        const dormant = series.find((s) => s.key === 'dormant')
        const newSeries = series.find((s) => s.key === 'new')
        expect(dormant?.visibility).toEqual({ excluded: true })
        expect(newSeries?.visibility).toBeUndefined()
    })

    it('falls back to "None" label when the result label is null', () => {
        const series = buildTrendsLifecycleSeries([{ id: 'new', status: 'new', label: null, data: [1] }])
        expect(series[0].label).toBe('None')
    })
})

describe('buildTrendsLifecycleConfig', () => {
    it.each([
        { isStacked: true, expectedLayout: 'stacked', expectedDiverging: true },
        { isStacked: false, expectedLayout: 'grouped', expectedDiverging: false },
    ])(
        'maps isStacked=$isStacked to barLayout=$expectedLayout / divergingStack=$expectedDiverging',
        ({ isStacked, expectedLayout, expectedDiverging }) => {
            const cfg = buildTrendsLifecycleConfig({ isStacked })
            expect(cfg.barLayout).toBe(expectedLayout)
            expect(cfg.divergingStack).toBe(expectedDiverging)
        }
    )

    it('builds the xAxis from interval/timezone/allDays', () => {
        const cfg = buildTrendsLifecycleConfig({
            isStacked: true,
            interval: 'day',
            timezone: 'UTC',
            allDays: ['2024-06-10', '2024-06-11'],
        })
        expect(cfg.xAxis).toEqual({
            timezone: 'UTC',
            interval: 'day',
            allDays: ['2024-06-10', '2024-06-11'],
        })
    })

    it('defaults interval to day and allDays to empty when omitted', () => {
        const cfg = buildTrendsLifecycleConfig({ isStacked: true })
        expect(cfg.xAxis).toEqual({ timezone: undefined, interval: 'day', allDays: [] })
    })

    it('forwards yAxisScaleType into the y-axis scale', () => {
        const cfg = buildTrendsLifecycleConfig({ isStacked: true, yAxisScaleType: 'log10' })
        expect(cfg.yAxis?.scale).toBe('log')
    })

    it('passes the tooltip config through unchanged', () => {
        const tooltip = { pinnable: true, placement: 'top' as const }
        const cfg = buildTrendsLifecycleConfig({ isStacked: true, tooltip })
        expect(cfg.tooltip).toEqual(tooltip)
    })

    it.each([
        { input: true, expected: true },
        { input: false, expected: false },
        {
            input: { formatter: (v: number) => `${v}!` },
            expected: { formatter: expect.any(Function) },
        },
    ])('forwards valueLabels=$input to the config', ({ input, expected }) => {
        const cfg = buildTrendsLifecycleConfig({ isStacked: true, valueLabels: input })
        expect(cfg.valueLabels).toEqual(expected)
    })
})

describe('shortenLifecycleLabel', () => {
    it.each([
        { input: 'Pageview - new', expected: 'New' },
        { input: 'Pageview - dormant', expected: 'Dormant' },
        { input: 'Logged in - returning', expected: 'Returning' },
        { input: 'just-a-label', expected: 'Just-a-label' },
        { input: undefined, expected: 'None' },
        { input: null, expected: 'None' },
    ])('returns $expected for $input', ({ input, expected }) => {
        expect(shortenLifecycleLabel(input)).toBe(expected)
    })
})
