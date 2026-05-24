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

const makeLifecycleResult = (overrides: Partial<TrendsLifecycleResultLike> = {}): TrendsLifecycleResultLike => ({
    id: overrides.status ?? overrides.id ?? 0,
    label: overrides.status ? `Pageview - ${overrides.status}` : 'Pageview - new',
    data: [1, 2, 3],
    status: 'new',
    ...overrides,
})

describe('buildTrendsLifecycleSeries', () => {
    it('orders series new → resurrecting → returning → dormant regardless of input order', () => {
        const results = [
            makeLifecycleResult({ id: 'dormant', status: 'dormant', data: [-1, -2, -3] }),
            makeLifecycleResult({ id: 'returning', status: 'returning' }),
            makeLifecycleResult({ id: 'new', status: 'new' }),
            makeLifecycleResult({ id: 'resurrecting', status: 'resurrecting' }),
        ]
        const series = buildTrendsLifecycleSeries(results)

        expect(series.map((s) => s.key)).toEqual(['new', 'resurrecting', 'returning', 'dormant'])
    })

    it('preserves dormant data as negative — diverging stack relies on the sign', () => {
        const results = [makeLifecycleResult({ id: 'dormant', status: 'dormant', data: [-5, -6, -7] })]
        const series = buildTrendsLifecycleSeries(results)

        expect(series[0].data).toEqual([-5, -6, -7])
    })

    it('uses fixed colors per lifecycle status, ignoring the data-color theme', () => {
        const results = [
            makeLifecycleResult({ id: 'new', status: 'new' }),
            makeLifecycleResult({ id: 'resurrecting', status: 'resurrecting' }),
            makeLifecycleResult({ id: 'returning', status: 'returning' }),
            makeLifecycleResult({ id: 'dormant', status: 'dormant', data: [-1, -2, -3] }),
        ]
        const series = buildTrendsLifecycleSeries(results)
        expect(series.map((s) => s.color)).toEqual(['#11ff11', '#22ff22', '#33ff33', '#44ff44'])
    })

    it('attaches meta from buildMeta with the original (pre-sort) index', () => {
        const results = [
            makeLifecycleResult({ id: 'dormant', status: 'dormant', data: [-1] }),
            makeLifecycleResult({ id: 'new', status: 'new' }),
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
        const results = [
            makeLifecycleResult({ id: 'new', status: 'new' }),
            makeLifecycleResult({ id: 'dormant', status: 'dormant', data: [-1] }),
        ]
        const series = buildTrendsLifecycleSeries(results, {
            getHidden: (r) => r.status === 'dormant',
        })
        const dormant = series.find((s) => s.key === 'dormant')
        const newSeries = series.find((s) => s.key === 'new')
        expect(dormant?.visibility).toEqual({ excluded: true })
        expect(newSeries?.visibility).toBeUndefined()
    })

    it('falls back to empty string label when result label is null', () => {
        const series = buildTrendsLifecycleSeries([makeLifecycleResult({ label: null, status: 'new' })])
        expect(series[0].label).toBe('')
    })
})

describe('buildTrendsLifecycleConfig', () => {
    it.each([
        { isGrouped: false, expectedLayout: 'stacked', expectedDiverging: true },
        { isGrouped: true, expectedLayout: 'grouped', expectedDiverging: false },
    ])(
        'maps isGrouped=$isGrouped to barLayout=$expectedLayout / divergingStack=$expectedDiverging',
        ({ isGrouped, expectedLayout, expectedDiverging }) => {
            const cfg = buildTrendsLifecycleConfig({ isGrouped })
            expect(cfg.barLayout).toBe(expectedLayout)
            expect(cfg.divergingStack).toBe(expectedDiverging)
        }
    )

    it('builds the xAxis from interval/timezone/allDays', () => {
        const cfg = buildTrendsLifecycleConfig({
            isGrouped: false,
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
        const cfg = buildTrendsLifecycleConfig({ isGrouped: false })
        expect(cfg.xAxis).toEqual({ timezone: undefined, interval: 'day', allDays: [] })
    })

    it('forwards yAxisScaleType into the y-axis scale', () => {
        const cfg = buildTrendsLifecycleConfig({ isGrouped: false, yAxisScaleType: 'log10' })
        expect(cfg.yAxis?.scale).toBe('log')
    })

    it('passes the tooltip config through unchanged', () => {
        const tooltip = { pinnable: true, placement: 'top' as const }
        const cfg = buildTrendsLifecycleConfig({ isGrouped: false, tooltip })
        expect(cfg.tooltip).toEqual(tooltip)
    })
})

describe('shortenLifecycleLabel', () => {
    it.each([
        { input: 'Pageview - new', expected: 'New' },
        { input: 'Pageview - dormant', expected: 'Dormant' },
        { input: 'Logged in - returning', expected: 'Returning' },
        { input: 'just-a-label', expected: 'Just-a-label' },
        { input: undefined, expected: 'None' },
    ])('returns $expected for $input', ({ input, expected }) => {
        expect(shortenLifecycleLabel(input)).toBe(expected)
    })
})
