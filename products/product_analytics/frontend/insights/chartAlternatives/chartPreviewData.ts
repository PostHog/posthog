import type { AnyResponseType, BoxPlotDatum, TrendsQuery } from '~/queries/schema/schema-general'
import { ChartDisplayType, type TrendResult } from '~/types'

import { breakdownProperties, hasTrendsFormula } from './chartDisplayOptions'

export interface ChartPreviewData {
    response: AnyResponseType
    sample: boolean
}

const SUMMABLE_MATHS = new Set(['total', 'sum'])

// Displays whose loaded result is the raw bucketed time series every other tile derives from.
export const RAW_TIME_SERIES_DISPLAYS = new Set<ChartDisplayType>([
    ChartDisplayType.ActionsLineGraph,
    ChartDisplayType.ActionsAreaGraph,
    ChartDisplayType.ActionsUnstackedBar,
    ChartDisplayType.ActionsBar,
    ChartDisplayType.ActionsStackedBar,
    ChartDisplayType.Metric,
])

const TOTAL_VALUE_DISPLAYS = new Set<ChartDisplayType>([
    ChartDisplayType.BoldNumber,
    ChartDisplayType.ActionsPie,
    ChartDisplayType.ActionsDonut,
    ChartDisplayType.ActionsBarValue,
])

const SINGLE_SERIES_DISPLAYS = new Set<ChartDisplayType>([ChartDisplayType.BoldNumber, ChartDisplayType.Metric])

const SAMPLE_COUNTRIES: [string, number][] = [
    ['US', 1840],
    ['GB', 920],
    ['DE', 610],
    ['IN', 540],
    ['CA', 430],
    ['FR', 380],
    ['BR', 310],
    ['AU', 260],
    ['JP', 220],
    ['NL', 170],
]

const SAMPLE_BOX_PLOT_DAYS = 7

type ResultShape = 'timeSeries' | 'totalValue' | 'heatmap' | 'boxPlot' | 'empty'

function resultsOf(response: AnyResponseType): TrendResult[] {
    const raw =
        (response as { result?: unknown; results?: unknown }).result ?? (response as { results?: unknown }).results
    return Array.isArray(raw) ? (raw as TrendResult[]) : []
}

// insightDataLogic rebuilds `result` from `results`, so both keys must carry the derived rows.
function withResults(response: AnyResponseType, results: unknown[]): AnyResponseType {
    return { ...(response as object), results, result: results } as AnyResponseType
}

function shapeOf(results: TrendResult[]): ResultShape {
    const first = results[0] as (TrendResult & { calendar_heatmap_data?: unknown; median?: number }) | undefined
    if (!first) {
        return 'empty'
    }
    if (first.calendar_heatmap_data) {
        return 'heatmap'
    }
    if (typeof first.median === 'number' && !Array.isArray(first.data)) {
        return 'boxPlot'
    }
    if (Array.isArray(first.data) && first.data.length > 0) {
        return 'timeSeries'
    }
    return first.aggregated_value != null ? 'totalValue' : 'empty'
}

function canSumBuckets(source: TrendsQuery, results: TrendResult[]): boolean {
    return (
        !hasTrendsFormula(source.trendsFilter) &&
        (source.trendsFilter?.smoothingIntervals ?? 1) <= 1 &&
        results.every((result) => result.action != null && SUMMABLE_MATHS.has(result.action.math ?? 'total'))
    )
}

function toTotalValue(result: TrendResult): TrendResult {
    return {
        ...result,
        data: [],
        count: 0,
        aggregated_value: (result.data ?? []).reduce((sum, value) => sum + value, 0),
    }
}

function toSlope(result: TrendResult): TrendResult {
    const ends = <T>(values: T[] | undefined): T[] =>
        values && values.length > 2 ? [values[0], values[values.length - 1]] : (values ?? [])
    return { ...result, data: ends(result.data), days: ends(result.days), labels: ends(result.labels) }
}

function toCumulative(result: TrendResult): TrendResult {
    let running = 0
    const data = (result.data ?? []).map((value) => (running += value))
    return { ...result, data, count: data[data.length - 1] ?? 0 }
}

function hasBreakdown(source: TrendsQuery): boolean {
    return !!source.breakdownFilter?.breakdown || !!source.breakdownFilter?.breakdowns?.length
}

function hasCountryCodeBreakdown(source: TrendsQuery): boolean {
    const properties = breakdownProperties(source.breakdownFilter)
    return properties.length === 1 && properties[0] === '$geoip_country_code'
}

function isCompleteBreakdown(response: AnyResponseType): boolean {
    return (response as { hasMore?: boolean }).hasMore === false
}

function sampleAction(result: TrendResult | undefined): Pick<TrendResult, 'action' | 'label'> {
    return { action: result?.action ?? null, label: result?.label ?? 'Sample' }
}

function sampleWorldMap(response: AnyResponseType, results: TrendResult[]): AnyResponseType {
    const base = sampleAction(results[0])
    return withResults(
        response,
        SAMPLE_COUNTRIES.map(([code, value]) => ({
            ...base,
            breakdown_value: code,
            data: [],
            days: [],
            labels: [],
            count: 0,
            aggregated_value: value,
        }))
    )
}

function sampleCalendarHeatmap(response: AnyResponseType, results: TrendResult[]): AnyResponseType {
    const data: { row: number; column: number; value: number }[] = []
    const rows = Array.from({ length: 7 }, () => 0)
    const columns = Array.from({ length: 24 }, () => 0)
    let all = 0
    for (let row = 0; row < 7; row++) {
        const weekday = row >= 1 && row <= 5
        for (let column = 0; column < 24; column++) {
            const working = column >= 8 && column <= 18
            const value = (weekday ? 40 : 12) + (working ? 60 : 0) + ((row * 7 + column * 3) % 11)
            data.push({ row, column, value })
            rows[row] += value
            columns[column] += value
            all += value
        }
    }
    return withResults(response, [
        {
            ...sampleAction(results[0]),
            data: [],
            days: [],
            labels: [],
            count: all,
            aggregated_value: all,
            calendar_heatmap_data: {
                data,
                rowAggregations: rows.map((value, row) => ({ row, value })),
                columnAggregations: columns.map((value, column) => ({ column, value })),
                allAggregations: all,
            },
        },
    ])
}

function sampleBoxPlot(response: AnyResponseType, results: TrendResult[]): AnyResponseType {
    const first = results[0]
    const days = first?.days?.length
        ? first.days
        : Array.from({ length: SAMPLE_BOX_PLOT_DAYS }, (_, i) => `Day ${i + 1}`)
    const labels = first?.labels?.length === days.length ? first.labels : days
    const data: BoxPlotDatum[] = days.map((day, index) => {
        const median = 40 + ((index * 13) % 17)
        return {
            day,
            label: labels[index],
            min: median - 25,
            p25: median - 10,
            median,
            p75: median + 12,
            max: median + 30,
            mean: median + 2,
            series_index: 0,
            series_label: first?.label ?? 'Sample',
        }
    })
    return withResults(response, data)
}

// The Metric runner adds a previous-period series for its change pill even when the query does not compare,
// so other displays must not inherit it.
function stripComparison(results: TrendResult[]): TrendResult[] {
    if (!results.some((result) => result.compare_label)) {
        return results
    }
    return results
        .filter((result) => result.compare_label !== 'previous')
        .map(({ compare_label: _label, compare: _compare, ...rest }) => rest as TrendResult)
}

// Builds the result a chart type would render, without a query: from the insight's loaded result, or from
// a raw time series for the same query when the loaded result is a total value. Returns null when neither
// can produce the display.
export function deriveChartPreview(
    display: ChartDisplayType,
    source: TrendsQuery,
    loaded: AnyResponseType,
    timeSeries: AnyResponseType | null = null
): ChartPreviewData | null {
    const loadedResults = resultsOf(loaded)
    const keepComparison =
        (display !== ChartDisplayType.SlopeGraph && !!source.compareFilter?.compare) ||
        display === ChartDisplayType.Metric
    const results = keepComparison ? loadedResults : stripComparison(loadedResults)
    const response = results === loadedResults ? loaded : withResults(loaded, results)
    const shape = shapeOf(results)
    const currentDisplay = source.trendsFilter?.display ?? ChartDisplayType.ActionsLineGraph
    const passthrough: ChartPreviewData = { response, sample: false }

    if (display === currentDisplay) {
        return passthrough
    }

    if (display === ChartDisplayType.CalendarHeatmap) {
        return shape === 'heatmap' ? passthrough : { response: sampleCalendarHeatmap(response, results), sample: true }
    }
    if (display === ChartDisplayType.BoxPlot) {
        return shape === 'boxPlot' ? passthrough : { response: sampleBoxPlot(response, results), sample: true }
    }

    // Only standard time-series displays return raw buckets. Cumulative and slope results have already transformed or
    // discarded buckets, so they need the remembered standard time-series response.
    let base: { response: AnyResponseType; results: TrendResult[] } | null = null
    if (shape === 'timeSeries' && RAW_TIME_SERIES_DISPLAYS.has(currentDisplay)) {
        base = { response, results }
    } else if (timeSeries) {
        const raw = resultsOf(timeSeries)
        const rows = keepComparison ? raw : stripComparison(raw)
        if (shapeOf(rows) === 'timeSeries') {
            base = { response: rows === raw ? timeSeries : withResults(timeSeries, rows), results: rows }
        }
    }

    if (display === ChartDisplayType.WorldMap) {
        if (!hasCountryCodeBreakdown(source)) {
            return { response: sampleWorldMap(response, results), sample: true }
        }
        if (shape === 'totalValue' && isCompleteBreakdown(response)) {
            return passthrough
        }
        if (!base || !isCompleteBreakdown(base.response) || !canSumBuckets(source, base.results)) {
            return { response: sampleWorldMap(response, results), sample: true }
        }
        return { response: withResults(base.response, base.results.map(toTotalValue)), sample: false }
    }

    if (display === ChartDisplayType.ActionsTable) {
        if (shape === 'totalValue') {
            return passthrough
        }
        return base && canSumBuckets(source, base.results)
            ? { response: withResults(base.response, base.results.map(toTotalValue)), sample: false }
            : null
    }

    if (SINGLE_SERIES_DISPLAYS.has(display) && hasBreakdown(source)) {
        return null
    }

    if (
        RAW_TIME_SERIES_DISPLAYS.has(display) ||
        display === ChartDisplayType.ActionsLineGraphCumulative ||
        display === ChartDisplayType.SlopeGraph
    ) {
        if (!base) {
            return null
        }
        let rows = base.results
        if (display === ChartDisplayType.ActionsLineGraphCumulative) {
            if (!canSumBuckets(source, rows)) {
                return null
            }
            rows = rows.map(toCumulative)
        } else if (display === ChartDisplayType.SlopeGraph) {
            if ((source.trendsFilter?.smoothingIntervals ?? 1) > 1 || hasBreakdown(source)) {
                return null
            }
            rows = rows.map(toSlope)
        }
        return { response: rows === base.results ? base.response : withResults(base.response, rows), sample: false }
    }

    if (TOTAL_VALUE_DISPLAYS.has(display)) {
        if (shape === 'totalValue') {
            return passthrough
        }
        if (!base || !canSumBuckets(source, base.results)) {
            return null
        }
        return { response: withResults(base.response, base.results.map(toTotalValue)), sample: false }
    }

    return passthrough
}
