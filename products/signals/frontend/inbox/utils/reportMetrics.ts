import { formatCurrency } from 'lib/utils/currency'
import { formatDurationMilliseconds, humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber, percentage, significantDecimalPlaces } from 'lib/utils/numbers'

import { CurrencyCode, InsightVizNode, Node, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { isInsightVizNode, isTrendsQuery } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

export type ReportMetricInsightQuery = InsightVizNode & { source: TrendsQuery }
type ReportMetricFormatting = Pick<ReportMetricApi, 'unit' | 'value_format'>

function finiteNumber(value: unknown): number | null {
    return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export function reportMetricAggregate(response: unknown): number | null {
    if (!response || typeof response !== 'object') {
        return null
    }

    const wrappedResponse = response as { result?: unknown; results?: unknown }
    const series = Array.isArray(wrappedResponse.result)
        ? wrappedResponse.result
        : Array.isArray(wrappedResponse.results)
          ? wrappedResponse.results
          : null
    const firstSeries = series?.[0]

    return firstSeries && typeof firstSeries === 'object'
        ? finiteNumber((firstSeries as { aggregated_value?: unknown }).aggregated_value)
        : null
}

function withUnit(value: string, unit: string | null): string {
    return unit ? `${value} ${unit}` : value
}

function isCurrencyCode(unit: string | null): unit is CurrencyCode {
    return !!unit && Object.values(CurrencyCode).includes(unit as CurrencyCode)
}

export function formatReportMetricValue(
    metric: ReportMetricFormatting,
    value: number | null | undefined
): string | null {
    if (value === null || value === undefined || !Number.isFinite(value)) {
        return null
    }

    const valueFormat = metric.value_format ?? 'number'
    const unit = metric.unit ?? null

    switch (valueFormat) {
        case 'count':
            return withUnit(humanFriendlyNumber(value, 0), unit)
        // Percentage and unbounded number values take decimal places from their magnitude, like the
        // insight chart axis (aggregationAxisFormat), so a small non-zero rate or number does not
        // round to `0%` or `0` and read as no impact.
        case 'percentage':
            return withUnit(percentage(value / 100, significantDecimalPlaces(value)), unit === '%' ? null : unit)
        case 'percentage_scaled':
            return withUnit(percentage(value, significantDecimalPlaces(value * 100)), unit === '%' ? null : unit)
        case 'duration':
            if (unit === 'ms') {
                return formatDurationMilliseconds(value)
            }
            if (unit === 's') {
                return humanFriendlyDuration(value, { maxUnits: 2, secondsPrecision: 3 })
            }
            return withUnit(humanFriendlyNumber(value, significantDecimalPlaces(value)), unit)
        case 'currency':
            return isCurrencyCode(unit) ? formatCurrency(value, unit) : withUnit(humanFriendlyNumber(value, 2), unit)
        case 'number':
            return withUnit(humanFriendlyNumber(value, significantDecimalPlaces(value)), unit)
    }
}

export function asReportMetricTrendsQuery(query: unknown): ReportMetricInsightQuery | null {
    if (!query || typeof query !== 'object' || !isInsightVizNode(query as Node)) {
        return null
    }

    const insightQuery = query as InsightVizNode
    if (!isTrendsQuery(insightQuery.source)) {
        return null
    }

    return insightQuery as ReportMetricInsightQuery
}

export function asReportMetricBarQuery(query: unknown): ReportMetricInsightQuery | null {
    const insightQuery = asReportMetricTrendsQuery(query)
    if (!insightQuery) {
        return null
    }

    const source: TrendsQuery = {
        ...insightQuery.source,
        kind: NodeKind.TrendsQuery,
        trendsFilter: {
            ...insightQuery.source.trendsFilter,
            display: ChartDisplayType.ActionsBar,
            // A report metric renders a single series, so a stored percent-stack view would normalize
            // every bucket to 100% and a hidden-legend index could blank the only series. Drop both
            // display leftovers before deriving the longitudinal bar.
            showPercentStackView: false,
            hiddenLegendIndexes: undefined,
        },
    }

    return {
        ...insightQuery,
        kind: NodeKind.InsightVizNode,
        source,
        full: false,
        showFilters: false,
        showHeader: false,
        showTable: false,
        showCorrelationTable: false,
        showResults: true,
        embedded: true,
    }
}

export function asReportMetricAggregateQuery(query: unknown): ReportMetricInsightQuery | null {
    const insightQuery = asReportMetricTrendsQuery(query)
    if (!insightQuery) {
        return null
    }

    const source: TrendsQuery = {
        ...insightQuery.source,
        kind: NodeKind.TrendsQuery,
        trendsFilter: {
            ...insightQuery.source.trendsFilter,
            // Time-series Trends responses intentionally expose interval buckets only. A total-value
            // display makes the backend aggregate over the whole date range, which is essential for
            // distinct-user metrics where summing the buckets would count returning people twice.
            display: ChartDisplayType.BoldNumber,
        },
    }

    return {
        ...insightQuery,
        kind: NodeKind.InsightVizNode,
        source,
        full: false,
        showFilters: false,
        showHeader: false,
        showTable: false,
        showCorrelationTable: false,
        showResults: true,
        embedded: true,
    }
}
