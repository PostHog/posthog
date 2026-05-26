import type { TimeSeriesBarChartConfig, TooltipConfig } from 'lib/hog-charts'

import {
    buildStickinessYAxisConfig,
    type StickinessYAxisScaleType,
} from '../StickinessLineChart/stickinessChartTransforms'

// Re-export so call sites don't need to know the shared helper lives next to the line port.
export { buildStickinessSeries as buildStickinessBarSeries } from '../StickinessLineChart/stickinessChartTransforms'

export interface BuildStickinessBarTimeSeriesConfigOpts {
    yAxisScaleType?: StickinessYAxisScaleType
    /** ActionsBar → stacked; ActionsUnstackedBar → grouped. Same `isGrouped` framing
     *  as `TrendsBarChart`; opposite polarity of the legacy `isStacked` flag in
     *  `ActionsLineGraph`. */
    isGrouped: boolean
    showGrid?: boolean
    valueLabels?: TimeSeriesBarChartConfig['valueLabels']
    tooltip?: TooltipConfig
}

export function buildStickinessBarTimeSeriesConfig(
    opts: BuildStickinessBarTimeSeriesConfigOpts
): TimeSeriesBarChartConfig {
    return {
        // No xAxis date config — labels are pre-formatted interval counts (Day 0, Day 1, …).
        yAxis: buildStickinessYAxisConfig({ yAxisScaleType: opts.yAxisScaleType, showGrid: opts.showGrid }),
        valueLabels: opts.valueLabels,
        barLayout: opts.isGrouped ? 'grouped' : 'stacked',
        tooltip: opts.tooltip,
    }
}
