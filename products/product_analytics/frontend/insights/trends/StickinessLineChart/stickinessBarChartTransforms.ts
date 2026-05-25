import type { Series, TimeSeriesBarChartConfig, TooltipConfig, YAxisConfig } from 'lib/hog-charts'

import { stickinessPercentFormatter, toPercentData, type StickinessResultLike } from './stickinessChartTransforms'

export interface BuildStickinessBarSeriesOpts<R extends StickinessResultLike, M = unknown> {
    getColor: (r: R, index: number) => string
    getHidden?: (r: R, index: number) => boolean
    buildMeta?: (r: R, index: number) => M
}

function buildStickinessBarMainSeries<R extends StickinessResultLike, M = unknown>(
    r: R,
    index: number,
    opts: BuildStickinessBarSeriesOpts<R, M>
): Series<M> {
    const excluded = opts.getHidden ? opts.getHidden(r, index) : false
    const meta = opts.buildMeta ? opts.buildMeta(r, index) : undefined
    return {
        key: String(r.id),
        label: r.label ?? '',
        data: toPercentData(r.data, r.count),
        color: opts.getColor(r, index),
        meta,
        visibility: excluded ? { excluded: true } : undefined,
    }
}

export function buildStickinessBarSeries<R extends StickinessResultLike, M = unknown>(
    results: R[],
    opts: BuildStickinessBarSeriesOpts<R, M>
): Series<M>[] {
    return results.map((r, index) => buildStickinessBarMainSeries(r, index, opts))
}

export interface BuildStickinessBarTimeSeriesConfigOpts {
    isGrouped: boolean
    yAxisScaleType?: string | null
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
        barLayout: opts.isGrouped ? 'grouped' : 'stacked',
        valueLabels: opts.valueLabels,
        tooltip: opts.tooltip,
    }
}
