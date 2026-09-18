import type { AnyResponseType, TrendsQuery } from '~/queries/schema/schema-general'
import { ChartDisplayType, type TrendResult } from '~/types'

import { breakdownProperties, hasTrendsFormula } from './chartDisplayOptions'
import { sampleBoxPlotRows, sampleCalendarHeatmapRows, sampleWorldMapRows } from './chartPreviewSamples'

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

interface PreviewRows {
    response: AnyResponseType
    results: TrendResult[]
}

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
        // The backend rounds each sampled bucket, so their sum can differ from a sampled total.
        (source.samplingFactor ?? 1) === 1 &&
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
    return breakdownProperties(source.breakdownFilter).length > 0
}

function hasCountryCodeBreakdown(source: TrendsQuery): boolean {
    const properties = breakdownProperties(source.breakdownFilter)
    return properties.length === 1 && properties[0] === '$geoip_country_code'
}

function isCompleteBreakdown(response: AnyResponseType): boolean {
    return (response as { hasMore?: boolean }).hasMore === false
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

function previewRows(response: AnyResponseType, keepComparison: boolean): PreviewRows {
    const raw = resultsOf(response)
    const results = keepComparison ? raw : stripComparison(raw)
    return { response: results === raw ? response : withResults(response, results), results }
}

// Only standard time-series displays return raw buckets. Cumulative and slope results have already transformed or
// discarded buckets, so they need the remembered standard time-series response.
function rawBuckets(source: TrendsQuery, loaded: PreviewRows, remembered: PreviewRows | null): PreviewRows | null {
    const currentDisplay = source.trendsFilter?.display ?? ChartDisplayType.ActionsLineGraph
    if (shapeOf(loaded.results) === 'timeSeries' && RAW_TIME_SERIES_DISPLAYS.has(currentDisplay)) {
        return loaded
    }
    return remembered && shapeOf(remembered.results) === 'timeSeries' ? remembered : null
}

type RowsNeeded = 'buckets' | 'totals' | 'heatmap' | 'boxPlot'

interface PreviewRecipe {
    needs: RowsNeeded
    when?: (source: TrendsQuery, rows: PreviewRows) => boolean
    transform?: (result: TrendResult) => TrendResult
    sampleRows?: (loaded: TrendResult[]) => unknown[]
}

const noBreakdown = (source: TrendsQuery): boolean => !hasBreakdown(source)
const summable = (source: TrendsQuery, rows: PreviewRows): boolean => canSumBuckets(source, rows.results)
const canSlope = (source: TrendsQuery): boolean =>
    (source.trendsFilter?.smoothingIntervals ?? 1) <= 1 && !hasBreakdown(source)
const completeCountries = (source: TrendsQuery, rows: PreviewRows): boolean =>
    hasCountryCodeBreakdown(source) && isCompleteBreakdown(rows.response)

// A display without a recipe renders the loaded result as it is.
const RECIPES: Partial<Record<ChartDisplayType, PreviewRecipe>> = {
    [ChartDisplayType.ActionsLineGraph]: { needs: 'buckets' },
    [ChartDisplayType.ActionsAreaGraph]: { needs: 'buckets' },
    [ChartDisplayType.ActionsUnstackedBar]: { needs: 'buckets' },
    [ChartDisplayType.ActionsBar]: { needs: 'buckets' },
    [ChartDisplayType.ActionsStackedBar]: { needs: 'buckets' },
    [ChartDisplayType.Metric]: { needs: 'buckets', when: noBreakdown },
    [ChartDisplayType.ActionsLineGraphCumulative]: { needs: 'buckets', when: summable, transform: toCumulative },
    [ChartDisplayType.SlopeGraph]: { needs: 'buckets', when: canSlope, transform: toSlope },
    [ChartDisplayType.BoldNumber]: { needs: 'totals', when: noBreakdown },
    [ChartDisplayType.ActionsPie]: { needs: 'totals' },
    [ChartDisplayType.ActionsDonut]: { needs: 'totals' },
    [ChartDisplayType.ActionsBarValue]: { needs: 'totals' },
    [ChartDisplayType.ActionsTable]: { needs: 'totals' },
    [ChartDisplayType.WorldMap]: { needs: 'totals', when: completeCountries, sampleRows: sampleWorldMapRows },
    [ChartDisplayType.CalendarHeatmap]: { needs: 'heatmap', sampleRows: sampleCalendarHeatmapRows },
    [ChartDisplayType.BoxPlot]: { needs: 'boxPlot', sampleRows: sampleBoxPlotRows },
}

// The rows that can satisfy a need, best first.
function candidateRows(
    needs: RowsNeeded,
    source: TrendsQuery,
    loaded: PreviewRows,
    buckets: PreviewRows | null
): PreviewRows[] {
    if (needs === 'buckets') {
        return buckets ? [buckets] : []
    }
    const candidates = shapeOf(loaded.results) === (needs === 'totals' ? 'totalValue' : needs) ? [loaded] : []
    if (needs === 'totals' && buckets && canSumBuckets(source, buckets.results)) {
        const results = buckets.results.map(toTotalValue)
        candidates.push({ response: withResults(buckets.response, results), results })
    }
    return candidates
}

// Builds the result a chart type would render, without a query: from the insight's loaded result, or from
// a raw time series for the same query when the loaded result is a total value. Returns null when neither
// can produce the display.
export function deriveChartPreview(
    display: ChartDisplayType,
    source: TrendsQuery,
    loadedResponse: AnyResponseType,
    timeSeriesResponse: AnyResponseType | null = null
): ChartPreviewData | null {
    const keepComparison =
        (display !== ChartDisplayType.SlopeGraph && !!source.compareFilter?.compare) ||
        display === ChartDisplayType.Metric

    const loaded = previewRows(loadedResponse, keepComparison)
    const recipe = RECIPES[display]

    if (!recipe || display === (source.trendsFilter?.display ?? ChartDisplayType.ActionsLineGraph)) {
        return { response: loaded.response, sample: false }
    }

    const remembered = timeSeriesResponse ? previewRows(timeSeriesResponse, keepComparison) : null
    const buckets = rawBuckets(source, loaded, remembered)
    const rows = candidateRows(recipe.needs, source, loaded, buckets).find(
        (candidate) => recipe.when?.(source, candidate) ?? true
    )

    if (rows) {
        const response = recipe.transform
            ? withResults(rows.response, rows.results.map(recipe.transform))
            : rows.response

        return { response, sample: false }
    }

    return recipe.sampleRows
        ? { response: withResults(loaded.response, recipe.sampleRows(loaded.results)), sample: true }
        : null
}
