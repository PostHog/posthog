import { DEFAULT_Y_AXIS_ID } from '@posthog/quill-charts'
import type { TooltipConfig, YAxisConfig } from '@posthog/quill-charts'

import { hexToRGBA } from 'lib/utils/colors'
import type { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'

import { ChartDisplayType } from '~/types'

import {
    buildStickinessLabels,
    buildStickinessLineTimeSeriesConfig,
    buildStickinessMainSeries,
    buildStickinessSeries,
    buildStickinessTooltipTitle,
    stickinessPercentFormatter,
    toPercentData,
    type StickinessResultLike,
} from './stickinessChartTransforms'

const RED = '#ff0000'

const makeResult = (overrides: Partial<StickinessResultLike> = {}): StickinessResultLike => ({
    id: 0,
    label: '$pageview',
    count: 100,
    data: [50, 30, 15, 5],
    days: [1, 2, 3, 4],
    ...overrides,
})

describe('stickinessChartTransforms', () => {
    describe('toPercentData', () => {
        it.each<[string, number[], number, number[]]>([
            ['typical share split', [50, 30, 15, 5], 100, [50, 30, 15, 5]],
            ['fractional output', [1, 2, 3], 4, [25, 50, 75]],
            ['count of 0 returns the raw values (avoids divide-by-zero)', [0, 0, 0], 0, [0, 0, 0]],
            ['empty data stays empty', [], 10, []],
        ])('%s', (_, data, count, expected) => {
            expect(toPercentData(data, count)).toEqual(expected)
        })

        it('returns a copy when count is 0 (no aliasing of the input array)', () => {
            const input = [1, 2, 3]
            const out = toPercentData(input, 0)
            expect(out).toEqual(input)
            expect(out).not.toBe(input)
        })
    })

    describe('buildStickinessMainSeries', () => {
        it('builds a single main series with data transformed to percentages', () => {
            const series = buildStickinessMainSeries(makeResult(), 0, { getColor: () => RED })

            expect(series).toMatchObject({
                key: '0',
                label: 'Pageview',
                data: [50, 30, 15, 5],
                color: RED,
                yAxisId: DEFAULT_Y_AXIS_ID,
            })
            expect(series.stroke).toBeUndefined()
            expect(series.fill).toBeUndefined()
            expect(series.visibility).toBeUndefined()
        })

        it('humanizes built-in event labels, leaving custom events untouched', () => {
            const core = buildStickinessMainSeries(makeResult({ label: '$pageview' }), 0, { getColor: () => RED })
            const custom = buildStickinessMainSeries(makeResult({ label: 'Napped' }), 0, { getColor: () => RED })
            expect(core.label).toBe('Pageview')
            expect(custom.label).toBe('Napped')
        })

        it.each([
            { compare_label: undefined, expectedColor: RED },
            { compare_label: 'current' as const, expectedColor: RED },
            { compare_label: 'previous' as const, expectedColor: hexToRGBA(RED, 0.5) },
        ])(
            'dims the compare-against-previous series to 0.5 alpha, leaving others full color (compare_label=$compare_label)',
            ({ compare_label, expectedColor }) => {
                const series = buildStickinessMainSeries(makeResult({ compare_label }), 0, { getColor: () => RED })
                expect(series.color).toBe(expectedColor)
            }
        )

        it('never sets a partial-stroke / in-progress tail (stickiness has no incomplete buckets)', () => {
            const series = buildStickinessMainSeries(makeResult({ data: [1, 2, 3, 4, 5] }), 0, { getColor: () => RED })
            expect(series.stroke).toBeUndefined()
        })

        it('marks a series excluded when getHidden returns true', () => {
            const series = buildStickinessMainSeries(makeResult(), 0, {
                getColor: () => RED,
                getHidden: () => true,
            })
            expect(series.visibility).toEqual({ excluded: true })
        })

        it('attaches the meta payload returned by buildMeta', () => {
            const meta = { breakdown_value: 'spike', order: 7 }
            const series = buildStickinessMainSeries(makeResult(), 0, {
                getColor: () => RED,
                buildMeta: () => meta,
            })
            expect(series.meta).toBe(meta)
        })

        it('falls back to empty string label when result has none', () => {
            const series = buildStickinessMainSeries(makeResult({ label: null }), 0, { getColor: () => RED })
            expect(series.label).toBe('')
        })

        it('keeps index 0 on the default y-axis even when showMultipleYAxes is true', () => {
            const series = buildStickinessMainSeries(makeResult(), 0, {
                getColor: () => RED,
                showMultipleYAxes: true,
            })
            expect(series.yAxisId).toBe(DEFAULT_Y_AXIS_ID)
        })

        it.each<[string, ChartDisplayType | undefined, Record<string, never> | undefined]>([
            ['ActionsAreaGraph sets fill', ChartDisplayType.ActionsAreaGraph, {}],
            ['ActionsLineGraph leaves fill undefined', ChartDisplayType.ActionsLineGraph, undefined],
            ['undefined display leaves fill undefined', undefined, undefined],
        ])('%s', (_, display, expected) => {
            const series = buildStickinessMainSeries(makeResult(), 0, {
                getColor: () => RED,
                display,
            })
            expect(series.fill).toEqual(expected)
        })

        it('passes the result index through to getColor and buildMeta', () => {
            const getColor = jest.fn(() => RED)
            const buildMeta = jest.fn(() => ({}))
            buildStickinessMainSeries(makeResult(), 3, { getColor, buildMeta })
            expect(getColor).toHaveBeenCalledWith(expect.anything(), 3)
            expect(buildMeta).toHaveBeenCalledWith(expect.anything(), 3)
        })
    })

    describe('buildStickinessSeries', () => {
        it('returns one main series per result', () => {
            const results = [makeResult({ id: 'a' }), makeResult({ id: 'b' })]
            const series = buildStickinessSeries(results, { getColor: () => RED })

            expect(series).toHaveLength(2)
            expect(series.map((s) => s.key)).toEqual(['a', 'b'])
        })

        it('assigns yAxisIds [left, y1, y2] across three results when showMultipleYAxes is true', () => {
            const results = [makeResult({ id: 'a' }), makeResult({ id: 'b' }), makeResult({ id: 'c' })]
            const series = buildStickinessSeries(results, { getColor: () => RED, showMultipleYAxes: true })

            expect(series.map((s) => s.yAxisId)).toEqual([DEFAULT_Y_AXIS_ID, 'y1', 'y2'])
        })

        it('transforms each result independently using its own count', () => {
            const results = [
                makeResult({ id: 'a', count: 200, data: [100, 50, 25, 25] }),
                makeResult({ id: 'b', count: 50, data: [10, 20, 10, 10] }),
            ]
            const series = buildStickinessSeries(results, { getColor: () => RED })
            expect(series[0].data).toEqual([50, 25, 12.5, 12.5])
            expect(series[1].data).toEqual([20, 40, 20, 20])
        })
    })

    describe('buildStickinessLabels', () => {
        it.each([
            ['day', 3, ['Day 0', 'Day 1', 'Day 2']],
            ['week', 2, ['Week 0', 'Week 1']],
            ['hour', 2, ['Hour 0', 'Hour 1']],
            ['month', 2, ['Month 0', 'Month 1']],
        ] as const)('emits "%s"-prefixed labels by index', (interval, count, expected) => {
            expect(buildStickinessLabels(count, interval)).toEqual(expected)
        })

        it('defaults to "Day" when interval is null/undefined', () => {
            expect(buildStickinessLabels(2, null)).toEqual(['Day 0', 'Day 1'])
            expect(buildStickinessLabels(2, undefined)).toEqual(['Day 0', 'Day 1'])
        })

        it('returns empty array when count is 0', () => {
            expect(buildStickinessLabels(0, 'day')).toEqual([])
        })
    })

    describe('stickinessPercentFormatter', () => {
        it.each([
            [0, '0.0%'],
            [50, '50.0%'],
            [85.16, '85.2%'],
            [100, '100.0%'],
        ])('formats %s → %s', (value, expected) => {
            expect(stickinessPercentFormatter(value)).toBe(expected)
        })
    })

    describe('buildStickinessTooltipTitle', () => {
        const makeDatum = (date_label?: string): SeriesDatum => ({
            id: 0,
            dataIndex: 0,
            datasetIndex: 0,
            order: 0,
            count: 0,
            date_label,
        })

        it.each<[string, string | null | undefined, SeriesDatum[], string]>([
            ['passes the integer day through for a day interval', 'day', [makeDatum('3')], 'Stickiness on day 3'],
            ['uses the query interval when set', 'week', [makeDatum('2')], 'Stickiness on week 2'],
            ['defaults the interval to "day" when null', null, [makeDatum('3')], 'Stickiness on day 3'],
            ['defaults the interval to "day" when undefined', undefined, [makeDatum('3')], 'Stickiness on day 3'],
            ['renders an empty day when date_label is missing', 'day', [makeDatum(undefined)], 'Stickiness on day '],
            ['renders an empty day when seriesData is empty', 'day', [], 'Stickiness on day '],
        ])('%s', (_, interval, seriesData, expected) => {
            expect(buildStickinessTooltipTitle(interval)(seriesData)).toBe(expected)
        })
    })

    describe('buildStickinessLineTimeSeriesConfig', () => {
        const TOOLTIP: TooltipConfig = { pinnable: true, placement: 'top' }

        it('returns yAxis with percent tick formatter and a linear scale by default', () => {
            const config = buildStickinessLineTimeSeriesConfig({})
            const yAxis = config.yAxis as YAxisConfig
            expect(yAxis).not.toBeUndefined()
            expect(yAxis.scale).toBe('linear')
            expect(yAxis.showGrid).toBe(true)
            expect(yAxis.tickFormatter).not.toBeUndefined()
            expect(yAxis.tickFormatter!(50)).toBe('50.0%')
        })

        it('switches the y-scale to log when yAxisScaleType is log10', () => {
            const config = buildStickinessLineTimeSeriesConfig({ yAxisScaleType: 'log10' })
            const yAxis = config.yAxis as YAxisConfig
            expect(yAxis).not.toBeUndefined()
            expect(yAxis.scale).toBe('log')
        })

        it('omits an xAxis date config — labels are pre-formatted interval counts', () => {
            const config = buildStickinessLineTimeSeriesConfig({})
            expect(config.xAxis).toBeUndefined()
        })

        it('passes through valueLabels, showCrosshair, and tooltip', () => {
            const formatter = (v: number): string => `${v}!`
            const config = buildStickinessLineTimeSeriesConfig({
                valueLabels: { formatter },
                showCrosshair: true,
                tooltip: TOOLTIP,
            })
            expect(config.valueLabels).toEqual({ formatter })
            expect(config.showCrosshair).toBe(true)
            expect(config.tooltip).toBe(TOOLTIP)
        })

        it('does not enable percentStackView (stickiness already pre-percents data)', () => {
            const config = buildStickinessLineTimeSeriesConfig({})
            expect(config.percentStackView).toBeUndefined()
        })

        it('does not emit derived CI / MA / trendLine configs (stickiness gates those out upstream)', () => {
            const config = buildStickinessLineTimeSeriesConfig({})
            expect(config.confidenceIntervals).toBeUndefined()
            expect(config.movingAverage).toBeUndefined()
            expect(config.trendLines).toBeUndefined()
        })

        it('does not emit goal lines (stickiness does not support them)', () => {
            const config = buildStickinessLineTimeSeriesConfig({})
            expect(config.goalLines).toBeUndefined()
        })
    })
})
