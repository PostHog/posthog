import type { Series, TooltipConfig } from 'lib/hog-charts'

import type { GoalLine as SchemaGoalLine } from '~/queries/schema/schema-general'

import {
    buildRetentionBarChartConfig,
    buildRetentionLineChartConfig,
    buildRetentionSeries,
    type RetentionSeriesMeta,
    type RetentionTrendSeriesEntry,
} from './retentionChartTransforms'

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
})
