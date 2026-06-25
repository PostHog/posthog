import type { TimeInterval, ValueLabelContext } from '@posthog/quill-charts'

import type { CurrencyCode, TrendsFilter as SchemaTrendsFilter } from '~/queries/schema/schema-general'
import type { IntervalType } from '~/types'

import type { YFormatterFields } from '../shared/trendsChartDisplayOptions'
import {
    buildLifecycleChartModel,
    buildLifecycleValueLabelFormatter,
    buildTrendsLifecycleConfig,
    buildTrendsLifecycleSeries,
    filterToggledLifecycleResults,
    lifecyclePrevActiveBaseByDataIndex,
    shortenLifecycleLabel,
    type TrendsLifecycleResultLike,
} from './trendsLifecycleChartTransforms'

// The neutral structural types in trendsLifecycleChartTransforms.ts exist so the shared chart code
// stays free of `~/` and `lib/` imports (the MCP Vite bundle can't resolve them). These helpers'
// return types enforce that the real schema types stay assignable to the neutral ones — if a schema
// field ever changes shape, the returns fail to compile and flag the drift here.
const asNeutralYFormatterFields = (f: NonNullable<SchemaTrendsFilter>): YFormatterFields => f
const asNeutralCurrency = (c: CurrencyCode): string => c
const asNeutralInterval = (i: IntervalType): TimeInterval => i

// Static color stub injected via `getColor` — the transform no longer reads CSS variables itself.
const STATUS_COLORS: Record<string, string> = {
    new: '#11ff11',
    resurrecting: '#22ff22',
    returning: '#33ff33',
    dormant: '#44ff44',
}
const getColor = (status: string | undefined): string => STATUS_COLORS[status ?? ''] ?? '#000000'

describe('schema type firewall', () => {
    it('keeps the schema TrendsFilter / CurrencyCode / IntervalType assignable to the neutral types', () => {
        expect(asNeutralYFormatterFields({ decimalPlaces: 2 })).toMatchObject({ decimalPlaces: 2 })
        expect(asNeutralCurrency('USD' as CurrencyCode)).toBe('USD')
        expect(asNeutralInterval('day')).toBe('day')
    })
})

describe('buildTrendsLifecycleSeries', () => {
    it('orders series dormant → returning → resurrecting → new regardless of input order', () => {
        const results: TrendsLifecycleResultLike[] = [
            { id: 'new', status: 'new', label: 'Pageview - new', data: [1, 2, 3] },
            { id: 'returning', status: 'returning', label: 'Pageview - returning', data: [1, 2, 3] },
            { id: 'dormant', status: 'dormant', label: 'Pageview - dormant', data: [-1, -2, -3] },
            { id: 'resurrecting', status: 'resurrecting', label: 'Pageview - resurrecting', data: [1, 2, 3] },
        ]
        const series = buildTrendsLifecycleSeries(results, { getColor })

        expect(series.map((s) => s.key)).toEqual(['dormant', 'returning', 'resurrecting', 'new'])
    })

    it('preserves dormant data as negative — diverging stack relies on the sign', () => {
        const series = buildTrendsLifecycleSeries(
            [{ id: 'dormant', status: 'dormant', label: 'Pageview - dormant', data: [-5, -6, -7] }],
            { getColor }
        )

        expect(series[0].data).toEqual([-5, -6, -7])
    })

    it('uses fixed colors per lifecycle status, ignoring the data-color theme', () => {
        const results: TrendsLifecycleResultLike[] = [
            { id: 'new', status: 'new', label: 'Pageview - new', data: [1, 2, 3] },
            { id: 'resurrecting', status: 'resurrecting', label: 'Pageview - resurrecting', data: [1, 2, 3] },
            { id: 'returning', status: 'returning', label: 'Pageview - returning', data: [1, 2, 3] },
            { id: 'dormant', status: 'dormant', label: 'Pageview - dormant', data: [-1, -2, -3] },
        ]
        const series = buildTrendsLifecycleSeries(results, { getColor })
        expect(series.map((s) => s.color)).toEqual(['#44ff44', '#33ff33', '#22ff22', '#11ff11'])
    })

    it('shortens series labels to capitalized status — used by both legend and tooltip', () => {
        const series = buildTrendsLifecycleSeries(
            [
                { id: 'new', status: 'new', label: 'Pageview - new', data: [1] },
                { id: 'dormant', status: 'dormant', label: 'Pageview - dormant', data: [-1] },
            ],
            { getColor }
        )
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
            getColor,
            buildMeta: (r, i) => {
                calls.push({ status: r.status!, index: i })
                return r.status
            },
        })
        // dormant was at original index 0, new at original index 1 — order is preserved in the callback.
        expect(calls).toEqual([
            { status: 'dormant', index: 0 },
            { status: 'new', index: 1 },
        ])
    })

    it('marks excluded series with visibility.excluded so the chart skips them', () => {
        const results: TrendsLifecycleResultLike[] = [
            { id: 'new', status: 'new', label: 'Pageview - new', data: [1] },
            { id: 'dormant', status: 'dormant', label: 'Pageview - dormant', data: [-1] },
        ]
        const series = buildTrendsLifecycleSeries(results, {
            getColor,
            getHidden: (r) => r.status === 'dormant',
        })
        const dormant = series.find((s) => s.key === 'dormant')
        const newSeries = series.find((s) => s.key === 'new')
        expect(dormant?.visibility).toEqual({ excluded: true })
        expect(newSeries?.visibility).toBeUndefined()
    })

    it('falls back to "None" label when the result label is null', () => {
        const series = buildTrendsLifecycleSeries([{ id: 'new', status: 'new', label: null, data: [1] }], { getColor })
        expect(series[0].label).toBe('None')
    })
})

describe('filterToggledLifecycleResults', () => {
    const rows = [
        { status: 'new', data: [1] },
        { status: 'returning', data: [2] },
        { status: 'dormant', data: [-3] },
    ]

    it('returns every row unchanged when no toggle is set', () => {
        expect(filterToggledLifecycleResults(rows, undefined)).toBe(rows)
    })

    it('keeps only rows whose status is toggled on', () => {
        expect(filterToggledLifecycleResults(rows, ['new', 'dormant'])).toEqual([
            { status: 'new', data: [1] },
            { status: 'dormant', data: [-3] },
        ])
    })

    it('drops rows without a status once a toggle is active', () => {
        const withUnstatused = [...rows, { status: undefined, data: [9] }]
        expect(filterToggledLifecycleResults(withUnstatused, ['new'])).toEqual([{ status: 'new', data: [1] }])
    })
})

describe('buildLifecycleChartModel', () => {
    const results: TrendsLifecycleResultLike[] = [
        { id: 'new', status: 'new', label: 'Pageview - new', data: [1, 2] },
        { id: 'dormant', status: 'dormant', label: 'Pageview - dormant', data: [-1, -2] },
    ]

    it('assembles series + config and passes the host labels through', () => {
        const model = buildLifecycleChartModel(results, {
            getColor,
            labels: ['Jun 1', 'Jun 2'],
            isStacked: true,
        })

        expect(model.labels).toEqual(['Jun 1', 'Jun 2'])
        expect(model.series.map((s) => s.key)).toEqual(['dormant', 'new'])
        expect(model.config.barLayout).toBe('stacked')
        expect(model.config.divergingStack).toBe(true)
    })

    it('applies the toggledLifecycles filter before building series', () => {
        const model = buildLifecycleChartModel(results, {
            getColor,
            labels: ['Jun 1', 'Jun 2'],
            isStacked: false,
            toggledLifecycles: ['new'],
        })

        expect(model.series.map((s) => s.key)).toEqual(['new'])
        expect(model.config.barLayout).toBe('grouped')
    })

    it('forwards the tooltip config through to the chart config', () => {
        const tooltip = { pinnable: true, placement: 'top' as const }
        const model = buildLifecycleChartModel(results, { getColor, labels: [], isStacked: true, tooltip })

        expect(model.config.tooltip).toBe(tooltip)
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

describe('buildLifecycleValueLabelFormatter', () => {
    const formatValue = (v: number): string => `${v}`
    // Diverging band at dataIndex 2: two active (positive) statuses summing to 80, plus dormant (-30).
    // Active segments share the active total (80) — dormant must NOT inflate that denominator, so
    // 20 → 25% (not 18% of the old abs total of 110). Dormant shares the previous-period base below.
    const band: ValueLabelContext = { rawValue: 20, bandValues: [20, 60, -30], isPercent: false }
    const dormantBaseByDataIndex = [0, 0, 40]

    it.each([
        { name: 'values only', showValues: true, showPercentages: false, expected: '20' },
        { name: 'values + percentages', showValues: true, showPercentages: true, expected: '20 (25%)' },
        { name: 'percentages only', showValues: false, showPercentages: true, expected: '25%' },
    ])('renders an active segment $name as "$expected" (share of active total, dormant excluded)', ({
        showValues,
        showPercentages,
        expected,
    }) => {
        const formatter = buildLifecycleValueLabelFormatter(formatValue, {
            showValues,
            showPercentages,
            dormantBaseByDataIndex,
        })
        expect(formatter(20, 0, 2, band)).toBe(expected)
    })

    it('shares the dormant segment against the previous-period active base (churn), not the band', () => {
        const formatter = buildLifecycleValueLabelFormatter(formatValue, {
            showValues: false,
            showPercentages: true,
            dormantBaseByDataIndex,
        })
        // |-30| / dormantBase[2]=40 = 75% — independent of the current band's own values.
        expect(formatter(-30, 2, 2, { rawValue: -30, bandValues: [20, 60, -30], isPercent: false })).toBe('75%')
    })

    it('skips the dormant percentage when there is no previous-period base (first period)', () => {
        const formatter = buildLifecycleValueLabelFormatter(formatValue, {
            showValues: false,
            showPercentages: true,
            dormantBaseByDataIndex,
        })
        expect(formatter(-30, 2, 0, { rawValue: -30, bandValues: [20, -30], isPercent: false })).toBe('')
    })

    it('returns an empty string (skip) for an active segment when the band has no active total', () => {
        const formatter = buildLifecycleValueLabelFormatter(formatValue, { showValues: false, showPercentages: true })
        expect(formatter(0, 0, 0, { rawValue: 0, bandValues: [0, -5], isPercent: false })).toBe('')
    })

    it('does not append percentages in percent layout (labels already express fractions)', () => {
        const formatter = buildLifecycleValueLabelFormatter(formatValue, { showValues: true, showPercentages: true })
        expect(formatter(0.2, 0, 0, { rawValue: 20, bandValues: [20, 80], isPercent: true })).toBe('0.2')
    })
})

describe('lifecyclePrevActiveBaseByDataIndex', () => {
    it('sums active statuses per period and shifts forward one (dormant churns against the prior base)', () => {
        const results: TrendsLifecycleResultLike[] = [
            { status: 'new', label: 'Pageview - new', data: [10, 20, 30] },
            { status: 'returning', label: 'Pageview - returning', data: [5, 6, 7] },
            { status: 'resurrecting', label: 'Pageview - resurrecting', data: [1, 2, 3] },
            // Dormant is negative and must be excluded from the active total entirely.
            { status: 'dormant', label: 'Pageview - dormant', data: [-4, -5, -6] },
        ]
        // active totals per period = [16, 28, 40]; shifted forward (base[d] = active[d-1]) → [0, 16, 28].
        expect(lifecyclePrevActiveBaseByDataIndex(results)).toEqual([0, 16, 28])
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
