import type { TooltipConfig } from 'lib/hog-charts'

import { buildStickinessBarTimeSeriesConfig } from './stickinessBarChartTransforms'

// `buildStickinessBarSeries` is a re-export of the line port's `buildStickinessSeries`,
// which is already covered in `../StickinessLineChart/stickinessChartTransforms.test.ts`.

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
