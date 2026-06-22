import type { Series, TooltipConfig, YAxisConfig } from '@posthog/quill-charts'

import type { RetentionTrendPayload } from 'scenes/retention/types'

import type { GoalLine as SchemaGoalLine } from '~/queries/schema/schema-general'

import type { GoalLineLike } from 'products/product_analytics/frontend/insights/trends/shared/trendsChartDisplayOptions'

import {
    buildRetentionBarChartConfig,
    buildRetentionChartModel,
    buildRetentionLineChartConfig,
    buildRetentionSeries,
    type RetentionCohortLike,
    computeRetentionSeriesValue,
    formatRetentionCohortLabel,
    type RetentionResultLike,
    type RetentionSeriesMeta,
    type RetentionTrendSeriesEntry,
    sortRetentionCohorts,
} from './retentionChartTransforms'

// The neutral structural types in retentionChartTransforms.ts exist so the shared chart code stays
// free of `~/` and `scenes/` imports (the MCP Vite bundle can't resolve them). These helpers' return
// types enforce that the real schema types stay assignable to the neutral ones — if a schema field
// ever changes shape, the returns fail to compile and flag the drift here rather than at a call site.
const asNeutralRetentionResult = (r: RetentionTrendPayload): RetentionResultLike => r
const asNeutralGoalLine = (g: SchemaGoalLine): GoalLineLike => g

const makeEntry = (overrides: Partial<RetentionTrendSeriesEntry> = {}): RetentionTrendSeriesEntry => ({
    count: 100,
    data: [100, 80, 60, 40, 20],
    days: ['2024-01-01', '2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05'],
    labels: ['Day 0', 'Day 1', 'Day 2', 'Day 3', 'Day 4'],
    index: 0,
    label: '2024-01-01',
    ...overrides,
})

const TOOLTIP: TooltipConfig = { pinnable: true, placement: 'top' }

describe('retentionChartTransforms', () => {
    describe('schema type firewall', () => {
        it('keeps the schema RetentionTrendPayload / GoalLine assignable to the neutral structural types', () => {
            expect(
                asNeutralRetentionResult({
                    count: 100,
                    data: [100, 50],
                    days: ['2024-01-01', '2024-01-02'],
                    labels: ['Day 0', 'Day 1'],
                    index: 0,
                })
            ).toMatchObject({ count: 100 })
            expect(asNeutralGoalLine({ label: 'goal', value: 10 })).toMatchObject({ label: 'goal', value: 10 })
        })
    })

    describe('buildRetentionSeries', () => {
        it('builds one series per payload, keyed by row index', () => {
            const series = buildRetentionSeries([makeEntry({ index: 0 }), makeEntry({ index: 1 })], {
                isIntervalView: false,
            })

            expect(series).toHaveLength(2)
            expect(series.map((s) => s.key)).toEqual(['retention-0', 'retention-1'])
            expect(series[0].data).toEqual([100, 80, 60, 40, 20])
        })

        it('uses the payload index as the row index, not the array position', () => {
            const series = buildRetentionSeries([makeEntry({ index: 7 })], { isIntervalView: false })

            expect(series[0].key).toBe('retention-7')
            expect(series[0].meta?.rowIndex).toBe(7)
        })

        it('falls back to the array position when the payload has no index', () => {
            const series = buildRetentionSeries([makeEntry({ index: undefined })], { isIntervalView: false })

            expect(series[0].key).toBe('retention-0')
            expect(series[0].meta?.rowIndex).toBe(0)
        })

        it.each<[string, Partial<RetentionTrendSeriesEntry>, string]>([
            [
                'breakdown value wins over the cohort label',
                { breakdown_value: 'Chrome', label: '2024-01-01' },
                'Chrome',
            ],
            [
                'cohort label is used when there is no breakdown',
                { breakdown_value: null, label: '2024-01-01' },
                '2024-01-01',
            ],
            [
                'empty-string breakdown falls through to the cohort label',
                { breakdown_value: '', label: '2024-01-01' },
                '2024-01-01',
            ],
        ])('label: %s', (_name, overrides, expected) => {
            const series = buildRetentionSeries([makeEntry(overrides)], { isIntervalView: false })
            expect(series[0].label).toBe(expected)
        })

        it('falls back to a "Cohort {index}" label when there is no breakdown or cohort label', () => {
            const series = buildRetentionSeries([makeEntry({ index: 3, breakdown_value: null, label: undefined })], {
                isIntervalView: false,
            })
            expect(series[0].label).toBe('Cohort 3')
        })

        it('dashes the in-progress tail at dataLength + offset for the normal view', () => {
            const series = buildRetentionSeries([makeEntry({ data: [1, 2, 3, 4, 5] })], {
                isIntervalView: false,
                incompletenessOffsetFromEnd: -2,
            })
            expect(series[0].stroke).toEqual({ partial: { fromIndex: 3 } })
        })

        it('skips the in-progress tail in interval view (each x-position is a different cohort)', () => {
            const series = buildRetentionSeries([makeEntry({ data: [1, 2, 3, 4, 5] })], {
                isIntervalView: true,
                incompletenessOffsetFromEnd: -2,
            })
            expect(series[0].stroke).toBeUndefined()
        })

        it.each<[string, number | undefined]>([
            ['no offset', undefined],
            ['a zero offset', 0],
            ['a positive offset', 1],
        ])('skips the in-progress tail for %s', (_name, incompletenessOffsetFromEnd) => {
            const series = buildRetentionSeries([makeEntry()], { isIntervalView: false, incompletenessOffsetFromEnd })
            expect(series[0].stroke).toBeUndefined()
        })

        it('carries cohort metadata through to series meta', () => {
            const series = buildRetentionSeries(
                [makeEntry({ index: 2, breakdown_value: 'Chrome', count: 42, label: '2024-01-03' })],
                { isIntervalView: false }
            )
            expect(series[0].meta).toEqual({
                rowIndex: 2,
                breakdown_value: 'Chrome',
                days: ['2024-01-01', '2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05'],
                cohortLabel: '2024-01-03',
                cohortCount: 42,
            })
        })
    })

    describe('buildRetentionLineChartConfig', () => {
        const baseSeries: Series<RetentionSeriesMeta>[] = buildRetentionSeries(
            [makeEntry({ index: 0 }), makeEntry({ index: 1 })],
            { isIntervalView: false }
        )

        it.each<[boolean, 'percentage' | 'numeric']>([
            [true, 'percentage'],
            [false, 'numeric'],
        ])('formats the y-axis based on isPercentage=%s -> %s', (isPercentage, format) => {
            const config = buildRetentionLineChartConfig({ isPercentage, series: baseSeries })
            expect(config.yAxis).toEqual({ format, scale: 'linear', showGrid: true })
        })

        it('emits one linear trend line per series when showTrendLines is true', () => {
            const config = buildRetentionLineChartConfig({
                isPercentage: true,
                series: baseSeries,
                showTrendLines: true,
            })
            expect(config.trendLines).toEqual([
                { seriesKey: 'retention-0', kind: 'linear' },
                { seriesKey: 'retention-1', kind: 'linear' },
            ])
        })

        it('omits trend lines when showTrendLines is false', () => {
            const config = buildRetentionLineChartConfig({ isPercentage: true, series: baseSeries })
            expect(config.trendLines).toBeUndefined()
        })

        it('omits trend lines when there are no series even if showTrendLines is true', () => {
            const config = buildRetentionLineChartConfig({ isPercentage: true, series: [], showTrendLines: true })
            expect(config.trendLines).toBeUndefined()
        })

        it('maps schema goal lines onto the config', () => {
            const goalLines: SchemaGoalLine[] = [{ label: 'Target', value: 50 }]
            const config = buildRetentionLineChartConfig({ isPercentage: true, series: baseSeries, goalLines })
            expect(config.goalLines).toEqual([expect.objectContaining({ label: 'Target', value: 50 })])
        })

        it.each<[string, SchemaGoalLine[] | null]>([
            ['null', null],
            ['an empty array', []],
        ])('leaves goal lines undefined when goalLines is %s', (_name, goalLines) => {
            const config = buildRetentionLineChartConfig({ isPercentage: true, series: baseSeries, goalLines })
            expect(config.goalLines).toBeUndefined()
        })

        it('passes the tooltip config through unchanged', () => {
            const config = buildRetentionLineChartConfig({ isPercentage: true, series: baseSeries, tooltip: TOOLTIP })
            expect(config.tooltip).toBe(TOOLTIP)
        })
    })

    describe('buildRetentionBarChartConfig', () => {
        const baseSeries: Series<RetentionSeriesMeta>[] = buildRetentionSeries([makeEntry()], { isIntervalView: false })

        it('lays bars out grouped so per-cohort bars stay side-by-side', () => {
            const config = buildRetentionBarChartConfig({ isPercentage: true, series: baseSeries })
            expect(config.barLayout).toBe('grouped')
        })

        it.each<[boolean, 'percentage' | 'numeric']>([
            [true, 'percentage'],
            [false, 'numeric'],
        ])('formats the y-axis based on isPercentage=%s -> %s', (isPercentage, format) => {
            const config = buildRetentionBarChartConfig({ isPercentage, series: baseSeries })
            expect(config.yAxis).toEqual({ format, scale: 'linear', showGrid: true })
        })

        it('maps schema goal lines onto the config', () => {
            const goalLines: SchemaGoalLine[] = [{ label: 'Target', value: 50 }]
            const config = buildRetentionBarChartConfig({ isPercentage: true, series: baseSeries, goalLines })
            expect(config.goalLines).toEqual([expect.objectContaining({ label: 'Target', value: 50 })])
        })

        it('passes the tooltip config through unchanged', () => {
            const config = buildRetentionBarChartConfig({ isPercentage: true, series: baseSeries, tooltip: TOOLTIP })
            expect(config.tooltip).toBe(TOOLTIP)
        })
    })

    describe('computeRetentionSeriesValue', () => {
        const values = [{ count: 100 }, { count: 50 }, { count: 0 }]

        it.each([
            { intervalIndex: 0, reference: 'total', expected: 100, desc: 'total: interval 0 is 100%' },
            { intervalIndex: 1, reference: 'total', expected: 50, desc: 'total: percentage of baseline' },
            { intervalIndex: 0, reference: 'previous', expected: 100, desc: 'previous: interval 0 is 100%' },
            { intervalIndex: 1, reference: 'previous', expected: 50, desc: 'previous: percentage of prior interval' },
        ])('count aggregation — $desc', ({ intervalIndex, reference, expected }) => {
            expect(computeRetentionSeriesValue(values, intervalIndex, 'count', reference)).toBe(expected)
        })

        it.each([
            { values: [{ count: 0 }, { count: 5 }], desc: 'baseline of 0' },
            { values: [{ count: 100 }], desc: 'missing interval' },
        ])('count aggregation returns 0 for $desc', ({ values: vals }) => {
            expect(computeRetentionSeriesValue(vals, 1, 'count', 'total')).toBe(0)
        })

        it('non-count aggregation surfaces aggregation_value directly', () => {
            expect(computeRetentionSeriesValue([{ count: 1, aggregation_value: 42 }], 0, 'sum', 'total')).toBe(42)
        })
    })

    describe('sortRetentionCohorts', () => {
        it('orders cohorts chronologically and keeps dateless cohorts last in original order', () => {
            const cohorts: RetentionCohortLike[] = [
                { date: '2024-03-01', values: [] },
                { date: null, values: [], breakdown_value: 'first-dateless' },
                { date: '2024-01-01', values: [] },
                { date: null, values: [], breakdown_value: 'second-dateless' },
            ]
            expect(sortRetentionCohorts(cohorts).map((c) => c.date ?? c.breakdown_value)).toEqual([
                '2024-01-01',
                '2024-03-01',
                'first-dateless',
                'second-dateless',
            ])
        })
    })

    describe('buildRetentionChartModel', () => {
        const colorAt = (i: number): string => `c${i}`
        const cohort = (date: string, counts: number[]): RetentionCohortLike => ({
            date,
            values: counts.map((count) => ({ count })),
        })

        it('caps to maxCohorts but reports the full total, and labels by period', () => {
            const cohorts = [
                cohort('2024-01-01', [100, 50]),
                cohort('2024-01-02', [80, 40]),
                cohort('2024-01-03', [60, 30]),
            ]
            const model = buildRetentionChartModel(cohorts, {
                aggregationType: 'count',
                reference: 'total',
                period: 'Day',
                getColor: colorAt,
                maxCohorts: 2,
            })

            expect(model.totalCohorts).toBe(3)
            expect(model.series).toHaveLength(2)
            expect(model.series.map((s) => s.color)).toEqual(['c0', 'c1'])
            expect(model.labels).toEqual(['Day 0', 'Day 1'])
            expect(model.series[0].data).toEqual([100, 50])
        })

        it('keeps every cohort when maxCohorts is omitted', () => {
            const cohorts = [
                cohort('2024-01-01', [100, 50]),
                cohort('2024-01-02', [80, 40]),
                cohort('2024-01-03', [60, 30]),
            ]
            const model = buildRetentionChartModel(cohorts, {
                aggregationType: 'count',
                reference: 'total',
                period: 'Day',
                getColor: colorAt,
            })

            expect(model.totalCohorts).toBe(3)
            expect(model.series).toHaveLength(3)
        })

        it.each([
            { aggregationType: 'count', expectedLabel: 'Retention %', expectedFormat: 'percentage' },
            { aggregationType: 'sum', expectedLabel: 'Sum', expectedFormat: 'numeric' },
            { aggregationType: 'avg', expectedLabel: 'Avg', expectedFormat: 'numeric' },
        ])('labels the y-axis for $aggregationType', ({ aggregationType, expectedLabel, expectedFormat }) => {
            const model = buildRetentionChartModel([cohort('2024-01-01', [100, 50])], {
                aggregationType,
                reference: 'total',
                period: 'Day',
                getColor: colorAt,
                maxCohorts: 6,
            })
            const lineYAxis = model.lineConfig.yAxis as YAxisConfig
            expect(lineYAxis?.label).toBe(expectedLabel)
            expect(model.barConfig.yAxis?.label).toBe(expectedLabel)
            expect(lineYAxis?.format).toBe(expectedFormat)
        })
    })

    describe('formatRetentionCohortLabel', () => {
        const withDate = (date: string | null, breakdown?: string | number | null): RetentionCohortLike => ({
            date,
            breakdown_value: breakdown,
            values: [{ count: 1 }],
        })

        // TZ is pinned to UTC in jest.config, so these locale strings are deterministic.
        it.each([
            {
                name: 'Day period',
                cohort: withDate('2024-03-15'),
                num: 1,
                period: 'Day',
                expected: 'Cohort 1 (Mar 15)',
            },
            {
                name: 'Week falls back to day format',
                cohort: withDate('2024-03-15'),
                num: 2,
                period: 'Week',
                expected: 'Cohort 2 (Mar 15)',
            },
            {
                name: 'Month period',
                cohort: withDate('2024-03-15'),
                num: 3,
                period: 'Month',
                expected: 'Cohort 3 (Mar 2024)',
            },
            {
                name: 'Hour period',
                cohort: withDate('2024-03-15T13:00:00Z'),
                num: 4,
                period: 'Hour',
                expected: 'Cohort 4 (Mar 15, 1 PM)',
            },
            {
                name: 'breakdown + date',
                cohort: withDate('2024-03-15', 'Chrome'),
                num: 1,
                period: 'Day',
                expected: 'Cohort 1 (Chrome, Mar 15)',
            },
            {
                name: 'breakdown, no date',
                cohort: withDate(null, 'Chrome'),
                num: 1,
                period: 'Day',
                expected: 'Cohort 1 (Chrome)',
            },
            {
                name: 'empty-string breakdown is ignored',
                cohort: withDate('2024-03-15', ''),
                num: 1,
                period: 'Day',
                expected: 'Cohort 1 (Mar 15)',
            },
            {
                name: 'invalid date, no breakdown',
                cohort: withDate('not-a-date'),
                num: 1,
                period: 'Day',
                expected: 'Cohort 1',
            },
            { name: 'null date, no breakdown', cohort: withDate(null), num: 7, period: 'Day', expected: 'Cohort 7' },
        ])('formats $name', ({ cohort, num, period, expected }) => {
            expect(formatRetentionCohortLabel(cohort, num, period)).toBe(expected)
        })
    })
})
