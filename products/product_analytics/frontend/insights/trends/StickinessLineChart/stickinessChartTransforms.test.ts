import { DEFAULT_Y_AXIS_ID } from 'lib/hog-charts'
import type { TooltipConfig } from 'lib/hog-charts'

import {
    buildStickinessLabels,
    buildStickinessLineTimeSeriesConfig,
    buildStickinessMainSeries,
    buildStickinessSeries,
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
                label: '$pageview',
                data: [50, 30, 15, 5],
                color: RED,
                yAxisId: DEFAULT_Y_AXIS_ID,
            })
            expect(series.stroke).toBeUndefined()
            expect(series.fill).toBeUndefined()
            expect(series.visibility).toBeUndefined()
        })

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

    describe('buildStickinessLineTimeSeriesConfig', () => {
        const TOOLTIP: TooltipConfig = { pinnable: true, placement: 'top' }

        it('returns yAxis with percent tick formatter and a linear scale by default', () => {
            const config = buildStickinessLineTimeSeriesConfig({})
            expect(config.yAxis).not.toBeUndefined()
            expect(config.yAxis!.scale).toBe('linear')
            expect(config.yAxis!.showGrid).toBe(true)
            expect(config.yAxis!.tickFormatter).not.toBeUndefined()
            expect(config.yAxis!.tickFormatter!(50)).toBe('50.0%')
        })

        it('switches the y-scale to log when yAxisScaleType is log10', () => {
            const config = buildStickinessLineTimeSeriesConfig({ yAxisScaleType: 'log10' })
            expect(config.yAxis).not.toBeUndefined()
            expect(config.yAxis!.scale).toBe('log')
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
