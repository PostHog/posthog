import type { Series, TimeSeriesBarChartConfig } from 'lib/hog-charts'
import { normalizeAxisLabel } from 'lib/hog-charts/utils/axis-labels'
import { hexToRGBA } from 'lib/utils'
import { COMPARE_PREVIOUS_DIM_OPACITY } from 'scenes/trends/viz/trendsAdapterConstants'

import type { CurrencyCode, GoalLine as SchemaGoalLine, TrendsFilter } from '~/queries/schema/schema-general'
import type { IntervalType } from '~/types'

import { schemaGoalLinesToConfigs } from '../shared/goalLinesAdapter'
import { buildTrendsYAxisConfig } from '../shared/trendsAxisFormat'

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
    return r.compare_label === 'previous' ? hexToRGBA(baseColor, COMPARE_PREVIOUS_DIM_OPACITY) : baseColor
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
    return {
        key: String(r.id),
        label: r.label ?? '',
        data,
        color,
        meta,
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
    trendsFilter?: TrendsFilter | null
    baseCurrency?: CurrencyCode
    isPercentStackView: boolean
    isGrouped: boolean
    yAxisScaleType?: string | null
    interval?: IntervalType | null
    timezone?: string
    allDays?: string[]
    xAxisLabel?: string | null
    yAxisLabel?: string | null
    goalLines?: SchemaGoalLine[] | null
    valueLabels?: TimeSeriesBarChartConfig['valueLabels']
    tooltip?: TimeSeriesBarChartConfig['tooltip']
}

export function buildTrendsBarTimeSeriesConfig(opts: BuildTrendsBarTimeSeriesConfigOpts): TimeSeriesBarChartConfig {
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
        },
        yAxis: {
            ...yAxis,
            label: normalizeAxisLabel(opts.yAxisLabel),
        },
        valueLabels: opts.valueLabels,
        goalLines: goalLineConfigs,
        barLayout: opts.isPercentStackView ? 'percent' : opts.isGrouped ? 'grouped' : 'stacked',
        tooltip: opts.tooltip,
    }
}

/** Key for the single collapsed series that carries every aggregated bar (per-bar identity lives
 *  in its `barColors`/`barLabels`/`barMeta`). Only needs to be unique within its one-element array. */
const AGGREGATED_SERIES_KEY = 'aggregated'

/** Separator between the series id and compare label in synthetic stacked-mode band keys. */
const BAND_KEY_SEP = '\u001f'

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
        // Default: every breakdown value is its own band. Emit ONE series of N values, one colored
        // bar per band, carrying per-bar identity via hog-charts barColors/barLabels/barMeta — O(n).
        const data = new Array<number>(n)
        const barColors = new Array<string | undefined>(n)
        const barLabels = new Array<string>(n)
        const barMeta = opts.buildMeta ? new Array<M>(n) : undefined
        for (let i = 0; i < n; i++) {
            const r = visible[i]
            const value = r.aggregated_value ?? 0
            data[i] = Number.isFinite(value) ? value : 0
            barColors[i] = resolveBarColor(r, i, opts)
            barLabels[i] = r.label ?? ''
            if (barMeta) {
                barMeta[i] = opts.buildMeta!(r, i)
            }
        }
        const series: Series<M>[] = [
            {
                key: AGGREGATED_SERIES_KEY,
                // Per-bar labels live in `barLabels`; the series-level label is never surfaced here.
                label: '',
                data,
                color: barColors[0],
                barColors,
                barLabels,
                barMeta,
            },
        ]
        return { series, labels: visible.map((_, i) => String(i)), displayLabels }
    }

    // Stacked breakdowns: multiple breakdown values share one band (keyed by series order +
    // compare_label) and genuinely stack into a single bar, so they can't collapse to one series.
    // Sparse-stacked: emit N series with data=0 except at their own slot — d3.stack reduces this
    // to one visible segment per band. Trade-off: only the last series gets rounded-corner caps.
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
