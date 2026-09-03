import { DEFAULT_Y_AXIS_ID } from '@posthog/quill-charts'
import type { Series, TimeSeriesLineChartConfig, TooltipConfig, YAxisConfig } from '@posthog/quill-charts'

import { capitalizeFirstLetter } from 'lib/utils/strings'
import type { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'

import { ChartDisplayType } from '~/types'

import { INSIGHT_TOOLTIP_CONFIG } from '../../shared/tooltipConfig'
import { COMPARE_PREVIOUS_DIM_OPACITY, dimHexColor } from '../../trends/shared/compareDimming'
import { humanizeSeriesLabel } from '../../trends/shared/humanizeSeriesLabel'
import { computeMagnitudeAxisIds } from '../../trends/shared/magnitudeAxisIds'
import { buildTrendsYAxisConfig } from '../../trends/shared/trendsAxisFormat'
import type { YFormatterFields } from '../../trends/shared/trendsChartDisplayOptions'

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

export function buildStickinessMainSeries<R extends StickinessResultLike, M = unknown>(
    r: R,
    index: number,
    opts: BuildStickinessSeriesOpts<R, M>,
    yAxisId: string = DEFAULT_Y_AXIS_ID
): Series<M> {
    const excluded = opts.getHidden ? opts.getHidden(r, index) : false
    const meta: M | undefined = opts.buildMeta ? opts.buildMeta(r, index) : undefined
    // Dim the compare-against-previous series so it recedes behind the current period, matching trends.
    const baseColor = opts.getColor(r, index)
    const color = r.compare_label === 'previous' ? dimHexColor(baseColor, COMPARE_PREVIOUS_DIM_OPACITY) : baseColor
    return {
        key: String(r.id),
        label: opts.getLabel ? opts.getLabel(r) : humanizeSeriesLabel(r.label),
        data: r.data,
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
    const yAxisIds = opts.showMultipleYAxes ? computeMagnitudeAxisIds(results.map((r) => r.data)) : undefined
    return results.map((r, index) => buildStickinessMainSeries(r, index, opts, yAxisIds?.[index]))
}

/** Produce per-bucket labels ("Day 0", "Day 1", …). The API's own "X day(s)" labels
 * duplicate the interval prefix when paired with a stickiness-style axis, so we
 * synthesize them from the bucket count. Mirrors `formatIntervalLabels` in the legacy LineGraph. */
export function buildStickinessLabels(count: number, interval: string | null | undefined): string[] {
    const prefix = capitalizeFirstLetter(interval ?? 'day')
    return Array.from({ length: count }, (_, i) => `${prefix} ${i}`)
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

/** Shared stickiness y-axis. Delegates to the trends formatter so stickiness shows a plain
 * count by default like every other insight type, while still respecting an explicit
 * aggregation axis format (currency, duration, etc.) if one is set on the insight. */
export function buildStickinessYAxisConfig(opts: {
    trendsFilter?: YFormatterFields | null
    baseCurrency?: string
    yAxisScaleType?: StickinessYAxisScaleType
    showGrid?: boolean
}): YAxisConfig {
    return buildTrendsYAxisConfig(opts.trendsFilter, false, opts.baseCurrency, {
        yAxisScaleType: opts.yAxisScaleType,
        showGrid: opts.showGrid ?? true,
    })
}

export interface BuildStickinessLineTimeSeriesConfigOpts {
    trendsFilter?: YFormatterFields | null
    baseCurrency?: string
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
        yAxis: buildStickinessYAxisConfig({
            trendsFilter: opts.trendsFilter,
            baseCurrency: opts.baseCurrency,
            yAxisScaleType: opts.yAxisScaleType,
            showGrid: opts.showGrid,
        }),
        valueLabels: opts.valueLabels,
        showCrosshair: opts.showCrosshair,
        tooltip: opts.tooltip,
    }
}
