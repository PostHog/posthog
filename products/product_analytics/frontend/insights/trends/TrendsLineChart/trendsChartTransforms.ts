import { DEFAULT_Y_AXIS_ID, movingAverageKey, normalizeAxisLabel } from '@posthog/quill-charts'
import type {
    ConfidenceIntervalConfig,
    MovingAverageConfig,
    Series,
    TimeInterval,
    TimeSeriesLineChartConfig,
    TooltipConfig,
    TrendLineConfig,
} from '@posthog/quill-charts'

import { schemaGoalLinesToConfigs } from '../shared/goalLinesAdapter'
import { humanizeSeriesLabel } from '../shared/humanizeSeriesLabel'
import { buildTrendsYAxisConfig } from '../shared/trendsAxisFormat'
import type { CiRangesFn, GoalLineLike, YFormatterFields } from '../shared/trendsChartDisplayOptions'

// Shape both IndexedTrendResult (kea) and TrendsResultItem (MCP) satisfy.
export interface TrendsResultLike {
    id?: string | number
    label?: string | null
    data: number[]
    days?: string[]
    compare?: boolean
    compare_label?: string | null
    action?: { order?: number } | null
    breakdown_value?: unknown
    filter?: unknown
}

export interface BuildTrendsSeriesOpts<R extends TrendsResultLike, M = unknown> {
    /** Area fill under each series (web maps `display === ActionsAreaGraph`). */
    isArea?: boolean
    showMultipleYAxes?: boolean
    // Negative number — index from the end where the in-progress tail begins. Omit to skip.
    incompletenessOffsetFromEnd?: number
    isStickiness?: boolean
    /** Canvas dash pattern applied to every series' line (per-insight chart style). */
    strokePattern?: number[]
    /** Marker radius drawn at each data point (per-insight chart style). Omit for no markers. */
    pointRadius?: number
    /** Fill under each series with a vertical gradient of the series color (per-insight chart style). */
    fillGradient?: boolean
    getColor: (r: R, index: number) => string
    getHidden?: (r: R, index: number) => boolean
    buildMeta?: (r: R, index: number) => M
    // Resolves the legend/series label (custom name + breakdown formatting). Hosts that lack the
    // breakdown/cohort deps (e.g. MCP) omit it and fall back to the raw humanized event name.
    getLabel?: (r: R) => string
}

// Shared between buildMainTrendsSeries (stroke.partial.fromIndex) and buildDerivedConfigs
// (trendline fitUpTo) — they must agree on the in-progress boundary.
export function computeDashedFromIndex(
    r: TrendsResultLike,
    opts: { isStickiness?: boolean; incompletenessOffsetFromEnd?: number }
): number | undefined {
    const isActiveSeries = !r.compare || r.compare_label !== 'previous'
    const isInProgress =
        !opts.isStickiness && opts.incompletenessOffsetFromEnd !== undefined && opts.incompletenessOffsetFromEnd < 0
    if (!isInProgress || !isActiveSeries) {
        return undefined
    }
    return r.data.length + (opts.incompletenessOffsetFromEnd as number)
}

export function buildMainTrendsSeries<R extends TrendsResultLike, M = unknown>(
    r: R,
    index: number,
    opts: BuildTrendsSeriesOpts<R, M>
): Series<M> {
    const dashedFromIndex = computeDashedFromIndex(r, opts)
    const yAxisId = opts.showMultipleYAxes && index > 0 ? `y${index}` : DEFAULT_Y_AXIS_ID
    const excluded = opts.getHidden ? opts.getHidden(r, index) : false
    const meta: M | undefined = opts.buildMeta ? opts.buildMeta(r, index) : undefined
    const stroke =
        dashedFromIndex !== undefined || opts.strokePattern
            ? {
                  pattern: opts.strokePattern,
                  partial: dashedFromIndex !== undefined ? { fromIndex: dashedFromIndex } : undefined,
              }
            : undefined
    return {
        key: String(r.id),
        label: opts.getLabel ? opts.getLabel(r) : humanizeSeriesLabel(r.label),
        data: r.data,
        color: opts.getColor(r, index),
        yAxisId,
        meta,
        fill: opts.fillGradient ? { gradient: true } : opts.isArea ? {} : undefined,
        stroke,
        points: opts.pointRadius !== undefined ? { radius: opts.pointRadius } : undefined,
        visibility: excluded ? { excluded: true } : undefined,
    }
}

export function buildTrendsSeries<R extends TrendsResultLike, M = unknown>(
    results: R[],
    opts: BuildTrendsSeriesOpts<R, M>
): Series<M>[] {
    return results.map((r, index) => buildMainTrendsSeries(r, index, opts))
}

export interface BuildDerivedConfigsOpts<R extends TrendsResultLike> {
    showConfidenceIntervals?: boolean
    confidenceLevel?: number
    // Injected so the transforms stay free of `lib/statistics`. CI is skipped when omitted.
    ciRanges?: CiRangesFn
    showMovingAverage?: boolean
    movingAverageIntervals?: number
    showTrendLines?: boolean
    isStickiness?: boolean
    incompletenessOffsetFromEnd?: number
    getHidden?: (r: R) => boolean
    getLabel?: (r: R) => string
}

export interface DerivedConfigs {
    confidenceIntervals?: ConfidenceIntervalConfig[]
    movingAverage?: MovingAverageConfig[]
    trendLines?: TrendLineConfig[]
    comparisonOf?: Record<string, string>
}

export function buildDerivedConfigs<R extends TrendsResultLike>(
    results: readonly R[],
    opts: BuildDerivedConfigsOpts<R>
): DerivedConfigs {
    const out: DerivedConfigs = {}
    if (!results.length) {
        return out
    }

    if (opts.showConfidenceIntervals && opts.ciRanges) {
        const ci = (opts.confidenceLevel ?? 95) / 100
        const ciRanges = opts.ciRanges
        out.confidenceIntervals = results.map((r) => {
            const [lower, upper] = ciRanges(r.data, ci)
            return { seriesKey: String(r.id), lower, upper }
        })
    }

    const includeMa = !!opts.showMovingAverage && opts.movingAverageIntervals !== undefined
    if (includeMa) {
        const window = opts.movingAverageIntervals as number
        out.movingAverage = results
            .filter((r) => !opts.getHidden?.(r))
            .filter((r) => r.data.length >= window)
            .map((r) => ({ seriesKey: String(r.id), window }))
    }

    if (opts.showTrendLines) {
        const trendLines: TrendLineConfig[] = []
        for (const r of results) {
            if (opts.getHidden?.(r)) {
                continue
            }
            const fitUpTo = computeDashedFromIndex(r, opts)
            trendLines.push({ seriesKey: String(r.id), kind: 'linear', fitUpTo })
            if (includeMa && r.data.length >= (opts.movingAverageIntervals as number)) {
                trendLines.push({
                    seriesKey: movingAverageKey(String(r.id)),
                    kind: 'linear',
                    label: `${opts.getLabel ? opts.getLabel(r) : humanizeSeriesLabel(r.label)} (Moving avg)`,
                })
            }
        }
        if (trendLines.length) {
            out.trendLines = trendLines
        }
    }

    const comparisonOf: Record<string, string> = {}
    for (const r of results) {
        if (r.compare && r.compare_label === 'previous') {
            const key = String(r.id)
            // Self-map: applyComparisonDimming only checks key presence; the paired primary
            // id isn't carried on TrendsResultLike.
            comparisonOf[key] = key
            if (includeMa && !opts.getHidden?.(r) && r.data.length >= (opts.movingAverageIntervals as number)) {
                comparisonOf[movingAverageKey(key)] = key
            }
        }
    }
    if (Object.keys(comparisonOf).length) {
        out.comparisonOf = comparisonOf
    }

    return out
}

export interface BuildTrendsLineTimeSeriesConfigOpts<R extends TrendsResultLike> {
    results: readonly R[]
    trendsFilter?: YFormatterFields | null
    baseCurrency?: string
    isPercentStackView: boolean
    isStickiness?: boolean
    yAxisScaleType?: string | null
    interval?: TimeInterval | null
    timezone?: string
    allDays?: string[]
    xAxisLabel?: string | null
    yAxisLabel?: string | null
    xAxisTickFormatter?: (value: string, index: number) => string | null
    goalLines?: GoalLineLike[] | null
    incompletenessOffsetFromEnd?: number
    getHidden?: (r: R) => boolean
    getLabel?: (r: R) => string

    showConfidenceIntervals?: boolean
    confidenceLevel?: number
    ciRanges?: CiRangesFn
    showMovingAverage?: boolean
    movingAverageIntervals?: number
    showTrendLines?: boolean

    valueLabels?: TimeSeriesLineChartConfig['valueLabels']

    /** Line interpolation override (per-insight chart style). Leave undefined for app defaults. */
    curve?: 'linear' | 'monotone'
    /** Gridlines override (per-insight chart style). Leave undefined for app defaults. */
    showGrid?: boolean

    showCrosshair?: boolean
    tooltip?: TooltipConfig
    legend?: TimeSeriesLineChartConfig['legend']
}

export function buildTrendsLineTimeSeriesConfig<R extends TrendsResultLike>(
    opts: BuildTrendsLineTimeSeriesConfigOpts<R>
): TimeSeriesLineChartConfig {
    const yAxis = buildTrendsYAxisConfig(opts.trendsFilter, opts.isPercentStackView, opts.baseCurrency, {
        yAxisScaleType: opts.yAxisScaleType,
        showGrid: opts.showGrid ?? true,
    })
    const goalLineConfigs = schemaGoalLinesToConfigs(opts.goalLines)
    const derivedConfigs = buildDerivedConfigs(opts.results, {
        showConfidenceIntervals: opts.showConfidenceIntervals,
        confidenceLevel: opts.confidenceLevel,
        ciRanges: opts.ciRanges,
        showMovingAverage: opts.showMovingAverage,
        movingAverageIntervals: opts.movingAverageIntervals,
        showTrendLines: opts.showTrendLines,
        isStickiness: opts.isStickiness,
        incompletenessOffsetFromEnd: opts.incompletenessOffsetFromEnd,
        getHidden: opts.getHidden,
        getLabel: opts.getLabel,
    })
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
        ...derivedConfigs,
        percentStackView: opts.isPercentStackView,
        curve: opts.curve,
        showGrid: opts.showGrid,
        showCrosshair: opts.showCrosshair,
        tooltip: opts.tooltip,
        legend: opts.legend,
    }
}
