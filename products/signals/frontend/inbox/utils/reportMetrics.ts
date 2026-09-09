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

export interface ReportMetricValueParts {
    value: string
    /** Suffix to show beside the value; null when the format already carries it (%, duration, currency). */
    unit: string | null
}

export function formatReportMetricParts(
    metric: ReportMetricFormatting,
    value: number | null | undefined
): ReportMetricValueParts | null {
    if (value === null || value === undefined || !Number.isFinite(value)) {
        return null
    }

    const valueFormat = metric.value_format ?? 'number'
    const unit = metric.unit ?? null

    switch (valueFormat) {
        case 'count':
            return { value: humanFriendlyNumber(value, 0), unit }
        // Percentage and unbounded number values take decimal places from their magnitude, like the
        // insight chart axis (aggregationAxisFormat), so a small non-zero rate or number does not
        // round to `0%` or `0` and read as no impact.
        case 'percentage':
            return { value: percentage(value / 100, significantDecimalPlaces(value)), unit: unit === '%' ? null : unit }
        case 'percentage_scaled':
            return {
                value: percentage(value, significantDecimalPlaces(value * 100)),
                unit: unit === '%' ? null : unit,
            }
        case 'duration':
            if (unit === 'ms') {
                return { value: formatDurationMilliseconds(value), unit: null }
            }
            if (unit === 's') {
                return { value: humanFriendlyDuration(value, { maxUnits: 2, secondsPrecision: 3 }), unit: null }
            }
            return { value: humanFriendlyNumber(value, significantDecimalPlaces(value)), unit }
        case 'currency':
            return isCurrencyCode(unit)
                ? { value: formatCurrency(value, unit), unit: null }
                : { value: humanFriendlyNumber(value, 2), unit }
        case 'number':
            return { value: humanFriendlyNumber(value, significantDecimalPlaces(value)), unit }
    }
}

export function formatReportMetricValue(
    metric: ReportMetricFormatting,
    value: number | null | undefined
): string | null {
    const parts = formatReportMetricParts(metric, value)
    return parts ? withUnit(parts.value, parts.unit) : null
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

function unitCarriesFormat(unit: string, valueFormat: NonNullable<ReportMetricApi['value_format']>): boolean {
    switch (valueFormat) {
        case 'percentage':
        case 'percentage_scaled':
            return unit === '%'
        case 'duration':
            return unit === 'ms' || unit === 's'
        case 'currency':
            return isCurrencyCode(unit)
        default:
            return false
    }
}

/** The one word an inbox row shows under the figure, such as `users`, `events`, or `seconds`. */
export function reportMetricUnitWord(metric: Pick<ReportMetricApi, 'kind' | 'unit' | 'value_format'>): string {
    const unit = metric.unit?.trim() ?? ''

    // An authored unit wins, except when the value format already renders it (a `%` sign, a duration
    // suffix, a currency symbol). Repeating it below the figure would read as `34% / %`.
    if (unit && !unitCarriesFormat(unit, metric.value_format ?? 'number')) {
        return unit
    }

    switch (metric.kind) {
        case 'affected_users':
            return 'users'
        case 'affected_sessions':
            return 'sessions'
        case 'occurrences':
            return 'events'
        case 'error_rate':
            return 'failure'
        case 'conversion_rate':
            return 'conversion'
        case 'duration':
            if (unit === 's') {
                return 'seconds'
            }
            if (unit === 'ms') {
                return 'ms'
            }
            return ''
        case 'revenue':
            return 'revenue'
        case 'custom':
            return ''
    }
}

export function reportMetricRowParts(
    metric: Pick<ReportMetricApi, 'kind' | 'unit' | 'value_format'>,
    value: number | null | undefined
): { value: string; unit: string } | null {
    const numericValue = finiteNumber(value)
    if (numericValue === null) {
        return null
    }

    const unit = reportMetricUnitWord(metric)
    const valueFormat = metric.value_format ?? 'number'

    switch (valueFormat) {
        case 'count':
            return { value: humanFriendlyNumber(numericValue, 0), unit }
        case 'percentage':
            return { value: percentage(numericValue / 100, significantDecimalPlaces(numericValue)), unit }
        case 'percentage_scaled':
            return { value: percentage(numericValue, significantDecimalPlaces(numericValue * 100)), unit }
        // The row stacks the unit word under the figure, so a duration stays a plain number in its own
        // unit. A composed `4m 47s` would collide with the `seconds` word below it.
        case 'duration':
            return { value: humanFriendlyNumber(numericValue, significantDecimalPlaces(numericValue)), unit }
        case 'currency': {
            const currency = metric.unit?.trim() ?? null
            return isCurrencyCode(currency)
                ? { value: formatCurrency(numericValue, currency), unit }
                : { value: humanFriendlyNumber(numericValue, 2), unit }
        }
        case 'number':
            return { value: humanFriendlyNumber(numericValue, significantDecimalPlaces(numericValue)), unit }
    }
}

const RELATIVE_WINDOW_RE = /^-(\d+)(h|d|w|m|y)$/
const RELATIVE_WINDOW_NOUNS: Record<string, string> = {
    h: 'hour',
    d: 'day',
    w: 'week',
    m: 'month',
    y: 'year',
}

/** Label the live query's relative window, such as `Last 14 days`. Null when it is not relative. */
export function reportMetricWindowLabel(query: unknown): string | null {
    if (!query || typeof query !== 'object') {
        return null
    }
    const source = (query as { source?: unknown }).source
    if (!source || typeof source !== 'object') {
        return null
    }
    const dateRange = (source as { dateRange?: unknown }).dateRange
    if (!dateRange || typeof dateRange !== 'object') {
        return null
    }

    const dateFrom = (dateRange as { date_from?: unknown }).date_from
    const match = typeof dateFrom === 'string' ? RELATIVE_WINDOW_RE.exec(dateFrom) : null
    if (!match) {
        return null
    }

    const amount = Number(match[1])
    const noun = RELATIVE_WINDOW_NOUNS[match[2]]
    return amount === 1 ? `Last ${noun}` : `Last ${amount} ${noun}s`
}

export type ReportMetricDeltaDirection = 'up' | 'down' | 'flat'
export type ReportMetricDeltaTone = 'good' | 'bad' | 'neutral'

export interface ReportMetricDelta {
    direction: ReportMetricDeltaDirection
    tone: ReportMetricDeltaTone
    /** Short change label such as `3.3×`, `+44%`, `-12%`, `+6 pts`, `No change`, `Up from 0`. */
    label: string
}

function compareDirection(current: number, previous: number): ReportMetricDeltaDirection {
    if (current > previous) {
        return 'up'
    }
    if (current < previous) {
        return 'down'
    }
    return 'flat'
}

function deltaTone(kind: ReportMetricApi['kind'], direction: ReportMetricDeltaDirection): ReportMetricDeltaTone {
    if (direction === 'flat' || kind === 'custom') {
        return 'neutral'
    }
    // Tone follows harm, not the arithmetic sign. More affected users is worse, more revenue is better.
    const goodDirection: ReportMetricDeltaDirection = kind === 'conversion_rate' || kind === 'revenue' ? 'up' : 'down'
    return direction === goodDirection ? 'good' : 'bad'
}

/** Null means the change is too small to report, so the caller renders `No change`. */
function pointsDeltaLabel(difference: number): string | null {
    const magnitude = Math.abs(difference)
    if (magnitude < 0.05) {
        return null
    }
    return `${difference > 0 ? '+' : '-'}${humanFriendlyNumber(magnitude, magnitude < 10 ? 1 : 0)} pts`
}

/** Null means the change is too small to report, so the caller renders `No change`. */
function ratioDeltaLabel(current: number, previous: number): string | null {
    if (previous === 0) {
        return current > 0 ? 'Up from 0' : null
    }

    const ratio = current / previous
    // A percentage stops being readable once a value more than doubles, so switch to a multiplier.
    if (ratio >= 2) {
        return `${humanFriendlyNumber(ratio, 1)}×`
    }

    const change = (ratio - 1) * 100
    if (Math.abs(change) < 0.5) {
        return null
    }
    return `${change > 0 ? '+' : '-'}${humanFriendlyNumber(Math.abs(change), 0)}%`
}

export function reportMetricDelta(
    metric: Pick<ReportMetricApi, 'kind' | 'value_format'>,
    current: number | null | undefined,
    previous: number | null | undefined
): ReportMetricDelta | null {
    const currentValue = finiteNumber(current)
    const previousValue = finiteNumber(previous)
    if (currentValue === null || previousValue === null) {
        return null
    }

    const valueFormat = metric.value_format ?? 'number'
    let label: string | null
    if (valueFormat === 'percentage' || valueFormat === 'percentage_scaled') {
        // A rate moves in percentage points, so a ratio between two rates would overstate the change.
        const scale = valueFormat === 'percentage_scaled' ? 100 : 1
        label = pointsDeltaLabel((currentValue - previousValue) * scale)
    } else {
        label = ratioDeltaLabel(currentValue, previousValue)
    }

    if (label === null) {
        return { direction: 'flat', tone: 'neutral', label: 'No change' }
    }

    const direction = compareDirection(currentValue, previousValue)
    return { direction, tone: deltaTone(metric.kind, direction), label }
}

function countPropertyFilters(properties: unknown): number {
    if (Array.isArray(properties)) {
        return properties.reduce<number>((count, item) => count + countPropertyFilters(item), 0)
    }
    if (!properties || typeof properties !== 'object') {
        return 0
    }
    // A property group nests its filters under `values`; a leaf filter is the one with a `key`.
    const node = properties as { values?: unknown; key?: unknown }
    if (Array.isArray(node.values)) {
        return countPropertyFilters(node.values)
    }
    return typeof node.key === 'string' ? 1 : 0
}

/** How many property filters narrow the query, across its series and the query itself. */
export function reportMetricFilterCount(query: ReportMetricInsightQuery): number {
    const seriesFilters = query.source.series.reduce<number>(
        (count, series) => count + countPropertyFilters((series as { properties?: unknown }).properties),
        0
    )
    return seriesFilters + countPropertyFilters(query.source.properties)
}
