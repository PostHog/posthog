import { DEFAULT_Y_AXIS_ID } from '@posthog/quill-charts'
import type { Series, TimeSeriesLineChartConfig, TooltipConfig, YAxisConfig } from '@posthog/quill-charts'

import { capitalizeFirstLetter } from 'lib/utils/strings'
import type { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'

import { ChartDisplayType } from '~/types'

import { INSIGHT_TOOLTIP_CONFIG } from '../../shared/tooltipConfig'
import { COMPARE_PREVIOUS_DIM_OPACITY, dimHexColor } from '../../trends/shared/compareDimming'
import { humanizeSeriesLabel } from '../../trends/shared/humanizeSeriesLabel'

// Shape both IndexedTrendResult (kea) and StickinessResultItem (MCP) satisfy.
export interface StickinessResultLike {
    id?: string | number
    label?: string | null
    data: number[]
    count: number
    days?: Array<string | number>
    compare_label?: string | null
    action?: { order?: number } | null
    breakdown_value?: unknown
    filter?: unknown
}

/** Stickiness y-axis scale options. Upstream (`trendsDataLogic`) exposes this as a
 *  loose `string | undefined`, so we keep that shape at the API boundary; only the
 *  literal `'log10'` is branched on inside `buildStickinessYAxisConfig`. */
export type StickinessYAxisScaleType = string | null | undefined

export interface BuildStickinessSeriesOpts<R extends StickinessResultLike, M = unknown> {
    showMultipleYAxes?: boolean
    display?: ChartDisplayType | null
    getColor: (r: R, index: number) => string
    getHidden?: (r: R, index: number) => boolean
    buildMeta?: (r: R, index: number) => M
    // Resolves the legend/series label (custom name + breakdown formatting). Hosts that lack the
    // breakdown/cohort deps (e.g. MCP) omit it and fall back to the raw humanized event name.
    getLabel?: (r: R) => string
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
    // Dim the compare-against-previous series so it recedes behind the current period, matching trends.
    const baseColor = opts.getColor(r, index)
    const color = r.compare_label === 'previous' ? dimHexColor(baseColor, COMPARE_PREVIOUS_DIM_OPACITY) : baseColor
    return {
        key: String(r.id),
        label: opts.getLabel ? opts.getLabel(r) : humanizeSeriesLabel(r.label),
        data: toPercentData(r.data, r.count),
        color,
        yAxisId,
        meta,
        fill: opts.display === ChartDisplayType.ActionsAreaGraph ? {} : undefined,
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
    const prefix = capitalizeFirstLetter(interval ?? 'day')
    return Array.from({ length: count }, (_, i) => `${prefix} ${i}`)
}

/** Emit `85.0%`-style ticks — legacy parity with `${value.toFixed(1)}%` in LineGraph. */
export function stickinessPercentFormatter(value: number): string {
    return `${value.toFixed(1)}%`
}

export const STICKINESS_TOOLTIP_CONFIG = INSIGHT_TOOLTIP_CONFIG

/** Stickiness `date` is an interval-count integer (1, 2, …), not a date.
 *  Render "Stickiness on {interval} {day}" so InsightTooltip doesn't try to
 *  format it as a calendar date (which would land on 1970-01-01). */
export function buildStickinessTooltipTitle(
    interval: string | null | undefined
): (seriesData: SeriesDatum[]) => string {
    return (seriesData) => {
        const day = seriesData[0]?.date_label ?? ''
        return `Stickiness on ${interval || 'day'} ${day}`
    }
}

/** Shared stickiness y-axis: percent tick formatter + linear/log scale toggle. */
export function buildStickinessYAxisConfig(opts: {
    yAxisScaleType?: StickinessYAxisScaleType
    showGrid?: boolean
}): YAxisConfig {
    return {
        scale: opts.yAxisScaleType === 'log10' ? 'log' : 'linear',
        showGrid: opts.showGrid ?? true,
        tickFormatter: stickinessPercentFormatter,
    }
}

export interface BuildStickinessLineTimeSeriesConfigOpts {
    yAxisScaleType?: StickinessYAxisScaleType
    showGrid?: boolean
    valueLabels?: TimeSeriesLineChartConfig['valueLabels']
    showCrosshair?: boolean
    tooltip?: TooltipConfig
}

export function buildStickinessLineTimeSeriesConfig(
    opts: BuildStickinessLineTimeSeriesConfigOpts
): TimeSeriesLineChartConfig {
    return {
        // No xAxis date config — labels are pre-formatted interval counts (Day 0, Day 1, …).
        yAxis: buildStickinessYAxisConfig({ yAxisScaleType: opts.yAxisScaleType, showGrid: opts.showGrid }),
        valueLabels: opts.valueLabels,
        showCrosshair: opts.showCrosshair,
        tooltip: opts.tooltip,
    }
}
