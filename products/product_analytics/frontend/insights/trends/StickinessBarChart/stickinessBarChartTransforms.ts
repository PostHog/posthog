import type { Series, TimeSeriesBarChartConfig, TooltipConfig, YAxisConfig } from 'lib/hog-charts'

import {
    type BuildStickinessSeriesOpts,
    buildStickinessMainSeries,
    type StickinessResultLike,
    stickinessPercentFormatter,
} from '../StickinessLineChart/stickinessChartTransforms'

/** One bar series per stickiness result. Data is pre-percent (share of series total)
 *  via `buildStickinessMainSeries`, matching the legacy `showPercentView` parity. */
export function buildStickinessBarSeries<R extends StickinessResultLike, M = unknown>(
    results: R[],
    opts: BuildStickinessSeriesOpts<R, M>
): Series<M>[] {
    return results.map((r, index) => buildStickinessMainSeries(r, index, opts))
}

export interface BuildStickinessBarTimeSeriesConfigOpts {
    yAxisScaleType?: string | null
    /** ActionsBar → stacked; ActionsUnstackedBar → grouped. Matches the legacy
     *  `isStacked = display !== ActionsUnstackedBar` decision in ActionsLineGraph. */
    isGrouped: boolean
    showGrid?: boolean
    valueLabels?: TimeSeriesBarChartConfig['valueLabels']
    tooltip?: TooltipConfig
}

export function buildStickinessBarTimeSeriesConfig(
    opts: BuildStickinessBarTimeSeriesConfigOpts
): TimeSeriesBarChartConfig {
    const yAxis: YAxisConfig = {
        scale: opts.yAxisScaleType === 'log10' ? 'log' : 'linear',
        showGrid: opts.showGrid ?? true,
        tickFormatter: stickinessPercentFormatter,
    }
    return {
        // No xAxis date config — labels are pre-formatted interval counts (Day 0, Day 1, …).
        yAxis,
        valueLabels: opts.valueLabels,
        barLayout: opts.isGrouped ? 'grouped' : 'stacked',
        tooltip: opts.tooltip,
    }
}
