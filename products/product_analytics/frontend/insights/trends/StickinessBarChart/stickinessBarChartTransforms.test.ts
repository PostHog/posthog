import type { TooltipConfig } from 'lib/hog-charts'

import { type StickinessResultLike } from '../StickinessLineChart/stickinessChartTransforms'
import { buildStickinessBarSeries, buildStickinessBarTimeSeriesConfig } from './stickinessBarChartTransforms'

const RED = '#ff0000'

const makeResult = (overrides: Partial<StickinessResultLike> = {}): StickinessResultLike => ({
    id: 0,
    label: '$pageview',
    count: 100,
    data: [50, 30, 15, 5],
    days: [1, 2, 3, 4],
    ...overrides,
})

describe('stickinessBarChartTransforms', () => {
    describe('buildStickinessBarSeries', () => {
        it('returns one series per result with pre-percent data (mirrors line port)', () => {
            const results = [
                makeResult({ id: 'a', count: 200, data: [100, 50, 25, 25] }),
                makeResult({ id: 'b', count: 50, data: [10, 20, 10, 10] }),
            ]
            const series = buildStickinessBarSeries(results, { getColor: () => RED })

            expect(series).toHaveLength(2)
            expect(series.map((s) => s.key)).toEqual(['a', 'b'])
            expect(series[0].data).toEqual([50, 25, 12.5, 12.5])
            expect(series[1].data).toEqual([20, 40, 20, 20])
        })

        it('marks a series excluded when getHidden returns true', () => {
            const series = buildStickinessBarSeries([makeResult()], {
                getColor: () => RED,
                getHidden: () => true,
            })
            expect(series[0].visibility).toEqual({ excluded: true })
        })

        it('attaches the meta payload returned by buildMeta', () => {
            const meta = { breakdown_value: 'spike', order: 7 }
            const series = buildStickinessBarSeries([makeResult()], {
                getColor: () => RED,
                buildMeta: () => meta,
            })
            expect(series[0].meta).toBe(meta)
        })

        it('falls back to empty string label when result label is null', () => {
            const series = buildStickinessBarSeries([makeResult({ label: null })], { getColor: () => RED })
            expect(series[0].label).toBe('')
        })

        it('passes the result index through to getColor and buildMeta', () => {
            const getColor = jest.fn(() => RED)
            const buildMeta = jest.fn(() => ({}))
            buildStickinessBarSeries([makeResult({ id: 'a' }), makeResult({ id: 'b' })], { getColor, buildMeta })
            expect(getColor).toHaveBeenCalledWith(expect.anything(), 0)
            expect(getColor).toHaveBeenCalledWith(expect.anything(), 1)
            expect(buildMeta).toHaveBeenCalledWith(expect.anything(), 0)
            expect(buildMeta).toHaveBeenCalledWith(expect.anything(), 1)
        })
    })

    describe('buildStickinessBarTimeSeriesConfig', () => {
        const TOOLTIP: TooltipConfig = { pinnable: true, placement: 'top' }

        it.each([
            { isGrouped: false, expected: 'stacked' as const },
            { isGrouped: true, expected: 'grouped' as const },
        ])('maps isGrouped=$isGrouped to barLayout=$expected', ({ isGrouped, expected }) => {
            const cfg = buildStickinessBarTimeSeriesConfig({ isGrouped })
            expect(cfg.barLayout).toBe(expected)
        })

        it('returns yAxis with percent tick formatter and a linear scale by default', () => {
            const config = buildStickinessBarTimeSeriesConfig({ isGrouped: false })
            expect(config.yAxis).not.toBeUndefined()
            expect(config.yAxis!.scale).toBe('linear')
            expect(config.yAxis!.showGrid).toBe(true)
            expect(config.yAxis!.tickFormatter).not.toBeUndefined()
            expect(config.yAxis!.tickFormatter!(50)).toBe('50.0%')
        })

        it('switches the y-scale to log when yAxisScaleType is log10', () => {
            const config = buildStickinessBarTimeSeriesConfig({ isGrouped: false, yAxisScaleType: 'log10' })
            expect(config.yAxis!.scale).toBe('log')
        })

        it('omits an xAxis date config — labels are pre-formatted interval counts', () => {
            const config = buildStickinessBarTimeSeriesConfig({ isGrouped: false })
            expect(config.xAxis).toBeUndefined()
        })

        it('passes through valueLabels and tooltip', () => {
            const formatter = (v: number): string => `${v}!`
            const config = buildStickinessBarTimeSeriesConfig({
                isGrouped: false,
                valueLabels: { formatter },
                tooltip: TOOLTIP,
            })
            expect(config.valueLabels).toEqual({ formatter })
            expect(config.tooltip).toBe(TOOLTIP)
        })

        it('does not emit goal lines (stickiness does not support them)', () => {
            const config = buildStickinessBarTimeSeriesConfig({ isGrouped: false })
            expect(config.goalLines).toBeUndefined()
        })
    })
})
