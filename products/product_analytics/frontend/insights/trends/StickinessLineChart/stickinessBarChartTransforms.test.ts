import type { TooltipConfig } from 'lib/hog-charts'

import {
    buildStickinessBarSeries,
    buildStickinessBarTimeSeriesConfig,
} from './stickinessBarChartTransforms'
import type { StickinessResultLike } from './stickinessChartTransforms'

const RED = '#ff0000'

const makeResult = (overrides: Partial<StickinessResultLike> = {}): StickinessResultLike => ({
    id: 0,
    label: '$pageview',
    count: 100,
    data: [50, 30, 15, 5],
    days: [1, 2, 3, 4],
    ...overrides,
})

describe('buildStickinessBarSeries', () => {
    it('returns one main series per result with data transformed to percentages', () => {
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

    it('returns raw values when count is 0 (no divide-by-zero)', () => {
        const series = buildStickinessBarSeries([makeResult({ count: 0, data: [0, 0, 0] })], { getColor: () => RED })
        expect(series[0].data).toEqual([0, 0, 0])
    })

    it('applies getColor to each result', () => {
        const colors = ['#aaa', '#bbb']
        const results = colors.map((_, i) => makeResult({ id: `r${i}` }))
        const series = buildStickinessBarSeries(results, { getColor: (_r, i) => colors[i] })
        expect(series.map((s) => s.color)).toEqual(colors)
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

    it('does not assign a yAxisId (bar charts use a single primary axis)', () => {
        const series = buildStickinessBarSeries([makeResult()], { getColor: () => RED })
        expect(series[0].yAxisId).toBeUndefined()
    })
})

describe('buildStickinessBarTimeSeriesConfig', () => {
    const TOOLTIP: TooltipConfig = { pinnable: true, placement: 'top' }

    it.each([
        { isGrouped: false, expected: 'stacked' },
        { isGrouped: true, expected: 'grouped' },
    ])('maps isGrouped=$isGrouped to barLayout=$expected', ({ isGrouped, expected }) => {
        const cfg = buildStickinessBarTimeSeriesConfig({ isGrouped })
        expect(cfg.barLayout).toBe(expected)
    })

    it('returns yAxis with percent tick formatter and a linear scale by default', () => {
        const cfg = buildStickinessBarTimeSeriesConfig({ isGrouped: false })
        expect(cfg.yAxis).not.toBeUndefined()
        expect(cfg.yAxis!.scale).toBe('linear')
        expect(cfg.yAxis!.showGrid).toBe(true)
        expect(cfg.yAxis!.tickFormatter).not.toBeUndefined()
        expect(cfg.yAxis!.tickFormatter!(50)).toBe('50.0%')
    })

    it('switches the y-scale to log when yAxisScaleType is log10', () => {
        const cfg = buildStickinessBarTimeSeriesConfig({ isGrouped: false, yAxisScaleType: 'log10' })
        expect(cfg.yAxis!.scale).toBe('log')
    })

    it('omits an xAxis date config — labels are pre-formatted interval counts', () => {
        const cfg = buildStickinessBarTimeSeriesConfig({ isGrouped: false })
        expect(cfg.xAxis).toBeUndefined()
    })

    it('passes through valueLabels and tooltip', () => {
        const formatter = (v: number): string => `${v}!`
        const cfg = buildStickinessBarTimeSeriesConfig({
            isGrouped: false,
            valueLabels: { formatter },
            tooltip: TOOLTIP,
        })
        expect(cfg.valueLabels).toEqual({ formatter })
        expect(cfg.tooltip).toBe(TOOLTIP)
    })

    it('does not emit goal lines (stickiness does not support them)', () => {
        const cfg = buildStickinessBarTimeSeriesConfig({ isGrouped: false })
        expect(cfg.goalLines).toBeUndefined()
    })
})
