import { type BarChartConfig } from '@posthog/quill-charts'

import { useChartConfig } from 'lib/charts/hooks'

export function useShareBarChartConfig(rowCount: number, totalCalls: number): BarChartConfig {
    return useChartConfig<BarChartConfig>(
        () => ({
            axisOrientation: 'horizontal',
            barLayout: 'grouped',
            hideXAxis: true,
            hideYAxis: true,
            showGrid: false,
            showAxisLines: false,
            showTickMarks: false,
            margins: { left: 0, right: 0, top: 20, bottom: 0 },
            barCornerRadius: 4,
            bars: {
                bandPadding: 0.65,
                maxBandRange: rowCount * 40,
                valueDomain: { min: 0, max: totalCalls || 1 },
                minBarSize: 6,
                minBarSizeScope: 'hover',
            },
        }),
        [rowCount, totalCalls]
    )
}
