import { DEFAULT_Y_AXIS_ID, normalizeAxisLabel } from '@posthog/quill-charts'
import type { Series, TimeInterval, TimeSeriesBarChartConfig, YAxisConfig } from '@posthog/quill-charts'

import { COMPARE_PREVIOUS_DIM_OPACITY, dimHexColor } from '../shared/compareDimming'
import { schemaGoalLinesToConfigs } from '../shared/goalLinesAdapter'
import { humanizeSeriesLabel } from '../shared/humanizeSeriesLabel'
import { buildTrendsYAxisConfig } from '../shared/trendsAxisFormat'
import type { GoalLineLike, YFormatterFields } from '../shared/trendsChartDisplayOptions'

// Shape both IndexedTrendResult (kea) and TrendsResultItem (MCP) satisfy.
export interface TrendsBarResultLike {
    id?: string | number
    label?: string | null
    data: number[]
    aggregated_value?: number
    days?: string[]
    compare?: boolean
    compare_label?: string | null
    action?: { order?: number } | null
    // Formula rows carry a top-level `order` instead of `action.order`.
    order?: number | null
    breakdown_value?: unknown
    filter?: unknown
}

export interface BuildTrendsBarSeriesOpts<R extends TrendsBarResultLike, M = unknown> {
    getColor: (r: R, index: number) => string
    getHidden?: (r: R, index: number) => boolean
    buildMeta?: (r: R, index: number) => M
    // Resolves the legend/series label (custom name + breakdown formatting). Hosts that lack the
    // breakdown/cohort deps (e.g. MCP) omit it and fall back to the raw humanized event name.
    getLabel?: (r: R) => string
    // Scale each series past the first against its own y-axis. Grouped (unstacked) bars only —
    // stacked layouts must share one axis, so the adapter never sets this for them.
    showMultipleYAxes?: boolean
}

export interface BuildTrendsBarAggregatedSeriesOpts<
    R extends TrendsBarResultLike,
    M = unknown,
> extends BuildTrendsBarSeriesOpts<R, M> {
    stackBreakdowns?: boolean
    getDisplayLabel?: (r: R, index: number) => string
}

/** Result color with the compare-previous dimming applied — shared by the per-series (time-series)
 *  and per-bar (aggregated) builders so both render identical colors. */
function resolveBarColor<R extends TrendsBarResultLike, M = unknown>(
    r: R,
    index: number,
    opts: BuildTrendsBarSeriesOpts<R, M>
): string {
    const baseColor = opts.getColor(r, index)
    return r.compare_label === 'previous' ? dimHexColor(baseColor, COMPARE_PREVIOUS_DIM_OPACITY) : baseColor
}

function buildMainTrendsBarSeries<R extends TrendsBarResultLike, M = unknown>(
    r: R,
    index: number,
    opts: BuildTrendsBarSeriesOpts<R, M>,
    data: number[]
): Series<M> {
    const color = resolveBarColor(r, index, opts)
    const excluded = opts.getHidden ? opts.getHidden(r, index) : false
    const meta = opts.buildMeta ? opts.buildMeta(r, index) : undefined
    const yAxisId = opts.showMultipleYAxes && index > 0 ? `y${index}` : DEFAULT_Y_AXIS_ID
    return {
        key: String(r.id),
        label: opts.getLabel ? opts.getLabel(r) : humanizeSeriesLabel(r.label),
        data,
        color,
        meta,
        yAxisId,
        visibility: excluded ? { excluded: true } : undefined,
    }
}

export function buildTrendsBarTimeSeries<R extends TrendsBarResultLike, M = unknown>(
    results: R[],
    opts: BuildTrendsBarSeriesOpts<R, M>
): Series<M>[] {
    return results.map((r, index) => buildMainTrendsBarSeries(r, index, opts, r.data))
}

export interface BuildTrendsBarTimeSeriesConfigOpts {
    trendsFilter?: YFormatterFields | null
    baseCurrency?: string
    isPercentStackView: boolean
    isGrouped: boolean
    yAxisScaleType?: string | null
    interval?: TimeInterval | null
    timezone?: string
    allDays?: string[]
    xAxisLabel?: string | null
    yAxisLabel?: string | null
    // Explicit x-axis tick formatter — used by hosts (e.g. MCP) that have label strings but no
    // interval/timezone for the auto date formatter. Mirrors the line config.
    xAxisTickFormatter?: (value: string, index: number) => string | null
    goalLines?: GoalLineLike[] | null
    valueLabels?: TimeSeriesBarChartConfig['valueLabels']
    tooltip?: TimeSeriesBarChartConfig['tooltip']
}

export function buildTrendsBarTimeSeriesConfig(
    opts: BuildTrendsBarTimeSeriesConfigOpts
): TimeSeriesBarChartConfig & { yAxis?: YAxisConfig } {
    const yAxis = buildTrendsYAxisConfig(opts.trendsFilter, opts.isPercentStackView, opts.baseCurrency, {
        yAxisScaleType: opts.yAxisScaleType,
        showGrid: true,
    })
    const goalLineConfigs = schemaGoalLinesToConfigs(opts.goalLines)
    return {
        xAxis: {
            label: normalizeAxisLabel(opts.xAxisLabel),
            timezone: opts.timezone,
            interval: opts.interval ?? 'day',
            allDays: opts.allDays ?? [],
            tickFormatter: opts.xAxisTickFormatter,
        },
        yAxis: {
            ...yAxis,
            label: normalizeAxisLabel(opts.yAxisLabel),
        },
        valueLabels: opts.valueLabels,
        goalLines: goalLineConfigs,
        barLayout: opts.isPercentStackView ? 'percent' : opts.isGrouped ? 'grouped' : 'stacked',
        // Stacked bars must preserve negative values (e.g. a `A*(-1)` formula) so they render
        // below the zero baseline instead of being clamped to 0. Only the stacked layout stacks.
        divergingStack: !opts.isPercentStackView && !opts.isGrouped,
        tooltip: opts.tooltip,
    }
}

/** Separator between the series id and compare label in synthetic stacked-mode band keys. */
const BAND_KEY_SEP = '\u001f'

export interface BuildTrendsBarChartModelOpts<
    R extends TrendsBarResultLike,
    M = unknown,
> extends BuildTrendsBarTimeSeriesConfigOpts {
    /** Final x-axis labels (the host formats them — kea dates vs the MCP `formatDate`). */
    labels: string[]
    getColor: (r: R, index: number) => string
    getHidden?: (r: R, index: number) => boolean
    buildMeta?: (r: R, index: number) => M
}

export interface TrendsBarChartModel<M = unknown> {
    series: Series<M>[]
    labels: string[]
    config: TimeSeriesBarChartConfig
}

/** Assembles the time-series bar chart model (series + config) in one call so the MCP visualizer
 *  builds the same series + config the web container assembles piecewise. */
export function buildTrendsBarChartModel<R extends TrendsBarResultLike, M = unknown>(
    results: R[],
    opts: BuildTrendsBarChartModelOpts<R, M>
): TrendsBarChartModel<M> {
    const series = buildTrendsBarTimeSeries<R, M>(results, {
        getColor: opts.getColor,
        getHidden: opts.getHidden,
        buildMeta: opts.buildMeta,
    })
    const config = buildTrendsBarTimeSeriesConfig(opts)
    return { series, labels: opts.labels, config }
}

export function buildTrendsBarAggregatedSeries<R extends TrendsBarResultLike, M = unknown>(
    results: R[],
    opts: BuildTrendsBarAggregatedSeriesOpts<R, M>
): { series: Series<M>[]; labels: string[]; displayLabels: string[] } {
    // Hidden results are dropped entirely — keeping them as `excluded` series would leave
    // a phantom band on the category axis with no bar.
    const visible = opts.getHidden ? results.filter((r, i) => !opts.getHidden!(r, i)) : results
    const displayLabels = visible.map((r, i) => {
        const base = opts.getDisplayLabel ? opts.getDisplayLabel(r, i) : (r.label ?? '')
        return r.compare_label ? `${base} - ${r.compare_label}` : base
    })
    const n = visible.length

    if (!opts.stackBreakdowns) {
        const bars = visible.map((r, i) => ({
            color: resolveBarColor(r, i, opts),
            label: r.label ?? '',
            meta: opts.buildMeta ? opts.buildMeta(r, i) : undefined,
        }))
        const series: Series<M>[] = [
            {
                key: 'aggregated',
                label: '',
                data: visible.map((r) => (Number.isFinite(r.aggregated_value) ? r.aggregated_value! : 0)),
                color: bars[0]?.color,
                bars,
            },
        ]
        return { series, labels: visible.map((_, i) => String(i)), displayLabels }
    }

    // Stacked breakdowns share a band and genuinely stack, so they stay as N sparse series.
    const labels = visible.map((r) => {
        const seriesId = r.action?.order ?? r.order ?? 0
        return `${seriesId}${BAND_KEY_SEP}${r.compare_label ?? ''}`
    })
    const series = visible.map((r, index) => {
        const data = new Array<number>(n).fill(0)
        const value = r.aggregated_value ?? 0
        if (Number.isFinite(value)) {
            data[index] = value
        }
        return buildMainTrendsBarSeries(r, index, opts, data)
    })
    return { series, labels, displayLabels }
}
