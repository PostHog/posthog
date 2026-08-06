import type { TooltipConfig } from '@posthog/quill-charts'

import { buildStickinessBarTimeSeriesConfig } from './stickinessBarChartTransforms'

// `buildStickinessBarSeries` is a re-export of the line port's `buildStickinessSeries` —
// covered in `../StickinessLineChart/stickinessChartTransforms.test.ts`. The yAxis builder
// is covered there too; the tests below stick to bar-specific behavior.

describe('buildStickinessBarTimeSeriesConfig', () => {
    it.each([
        { isGrouped: false, expected: 'stacked' as const },
        { isGrouped: true, expected: 'grouped' as const },
    ])('maps isGrouped=$isGrouped to barLayout=$expected', ({ isGrouped, expected }) => {
        expect(buildStickinessBarTimeSeriesConfig({ isGrouped }).barLayout).toBe(expected)
    })

    it('omits the xAxis date config (labels are pre-formatted interval counts)', () => {
        expect(buildStickinessBarTimeSeriesConfig({ isGrouped: false }).xAxis).toBeUndefined()
    })

    it('delegates the yAxis to the shared stickiness builder (percent + scale + grid)', () => {
        const cfg = buildStickinessBarTimeSeriesConfig({ isGrouped: false, yAxisScaleType: 'log10' })
        expect(cfg.yAxis!.scale).toBe('log')
        expect(cfg.yAxis!.tickFormatter!(50)).toBe('50.0%')
    })

    it('passes through valueLabels and tooltip', () => {
        const formatter = (v: number): string => `${v}!`
        const tooltip: TooltipConfig = { pinnable: true, placement: 'top' }
        const cfg = buildStickinessBarTimeSeriesConfig({
            isGrouped: false,
            valueLabels: { formatter },
            tooltip,
        })
        expect(cfg.valueLabels).toEqual({ formatter })
        expect(cfg.tooltip).toBe(tooltip)
    })
})
