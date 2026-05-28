import type { TimeSeriesBarChartConfig, TooltipConfig } from 'lib/hog-charts'

import {
    buildStickinessSeries,
    buildStickinessYAxisConfig,
    type StickinessYAxisScaleType,
} from '../StickinessLineChart/stickinessChartTransforms'

export { buildStickinessSeries as buildStickinessBarSeries }

export interface BuildStickinessBarTimeSeriesConfigOpts {
    yAxisScaleType?: StickinessYAxisScaleType
    /** ActionsBar → stacked; ActionsUnstackedBar → grouped. */
    isGrouped: boolean
    showGrid?: boolean
    valueLabels?: TimeSeriesBarChartConfig['valueLabels']
    tooltip?: TooltipConfig
}

export function buildStickinessBarTimeSeriesConfig(
    opts: BuildStickinessBarTimeSeriesConfigOpts
): TimeSeriesBarChartConfig {
    // No xAxis date config — labels are pre-formatted interval counts (Day 0, Day 1, …).
    return {
        yAxis: buildStickinessYAxisConfig({ yAxisScaleType: opts.yAxisScaleType, showGrid: opts.showGrid }),
        valueLabels: opts.valueLabels,
        barLayout: opts.isGrouped ? 'grouped' : 'stacked',
        tooltip: opts.tooltip,
    }
}
