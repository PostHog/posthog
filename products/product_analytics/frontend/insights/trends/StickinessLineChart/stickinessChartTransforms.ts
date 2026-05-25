import { DEFAULT_Y_AXIS_ID } from 'lib/hog-charts'
import type { Series, TimeSeriesLineChartConfig, TooltipConfig, YAxisConfig } from 'lib/hog-charts'

// Shape both IndexedTrendResult (kea) and StickinessResultItem (MCP) satisfy.
export interface StickinessResultLike {
    id?: string | number
    label?: string | null
    data: number[]
    count: number
    days?: Array<string | number>
    action?: { order?: number } | null
    breakdown_value?: unknown
    filter?: unknown
}

export interface BuildStickinessSeriesOpts<R extends StickinessResultLike, M = unknown> {
    showMultipleYAxes?: boolean
    getColor: (r: R, index: number) => string
    getHidden?: (r: R, index: number) => boolean
    buildMeta?: (r: R, index: number) => M
}

/** Convert raw counts to percentages of `count`. Mirrors the legacy `showPercentView`
 * behavior in LineGraph: each y-value becomes its share of the series total. */
export function toPercentData(data: number[], count: number): number[] {
    if (!count) {
        return data.slice()
    }
    return data.map((v) => (v / count) * 100)
}

export function buildStickinessMainSeries<R extends StickinessResultLike, M = unknown>(
    r: R,
    index: number,
    opts: BuildStickinessSeriesOpts<R, M>
): Series<M> {
    const yAxisId = opts.showMultipleYAxes && index > 0 ? `y${index}` : DEFAULT_Y_AXIS_ID
    const excluded = opts.getHidden ? opts.getHidden(r, index) : false
    const meta: M | undefined = opts.buildMeta ? opts.buildMeta(r, index) : undefined
    return {
        key: String(r.id),
        label: r.label ?? '',
        data: toPercentData(r.data, r.count),
        color: opts.getColor(r, index),
        yAxisId,
        meta,
        visibility: excluded ? { excluded: true } : undefined,
    }
}

export function buildStickinessSeries<R extends StickinessResultLike, M = unknown>(
    results: R[],
    opts: BuildStickinessSeriesOpts<R, M>
): Series<M>[] {
    return results.map((r, index) => buildStickinessMainSeries(r, index, opts))
}

/** Produce per-bucket labels ("Day 0", "Day 1", …). The API's own "X day(s)" labels
 * duplicate the interval prefix when paired with a stickiness-style axis, so we
 * synthesize them from the bucket count. Mirrors `formatIntervalLabels` in the legacy LineGraph. */
export function buildStickinessLabels(count: number, interval: string | null | undefined): string[] {
    const unit = interval ?? 'day'
    const prefix = `${unit.slice(0, 1).toUpperCase()}${unit.slice(1)}`
    return Array.from({ length: count }, (_, i) => `${prefix} ${i}`)
}

/** Emit `85.0%`-style ticks — legacy parity with `${value.toFixed(1)}%` in LineGraph. */
export function stickinessPercentFormatter(value: number): string {
    return `${value.toFixed(1)}%`
}

export interface BuildStickinessLineTimeSeriesConfigOpts {
    yAxisScaleType?: string | null
    showGrid?: boolean
    valueLabels?: TimeSeriesLineChartConfig['valueLabels']
    showCrosshair?: boolean
    tooltip?: TooltipConfig
}

export function buildStickinessLineTimeSeriesConfig(
    opts: BuildStickinessLineTimeSeriesConfigOpts
): TimeSeriesLineChartConfig {
    const yAxis: YAxisConfig = {
        scale: opts.yAxisScaleType === 'log10' ? 'log' : 'linear',
        showGrid: opts.showGrid ?? true,
        tickFormatter: stickinessPercentFormatter,
    }
    return {
        // No xAxis date config — labels are pre-formatted interval counts (Day 0, Day 1, …).
        yAxis,
        valueLabels: opts.valueLabels,
        showCrosshair: opts.showCrosshair,
        tooltip: opts.tooltip,
    }
}
