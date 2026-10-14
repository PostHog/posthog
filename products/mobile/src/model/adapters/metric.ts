import type { ProjectScope, ReportChartApi, ReportMetricApi } from '@/api/reports'
import { asRecord, isRecord } from '@/lib/records'

import type {
    MetricChartKind,
    MetricData,
    MetricFormat,
    MetricInterval,
    MetricSeries,
    MetricSnapshot,
    MetricValueFormat,
    MetricView,
    ReportChartView,
} from '../types'
import { groupThousands } from './text'

export interface MetricInput {
    title: string
    role: string
    value: number | null
    series: number[] | null
    value_format: string
    unit: string | null
    caption: string | null
    query?: unknown
}

const CURRENCY_SYMBOLS: Record<string, string> = { USD: '$', EUR: '€', GBP: '£' }

function compactAmount(value: number): string {
    const size = Math.abs(value)
    if (size >= 1_000_000) {
        return `${groupThousands(value / 1_000_000, 1)}M`
    }
    if (size >= 10_000) {
        return `${groupThousands(value / 1_000, 0)}k`
    }
    return groupThousands(value, 2)
}

export function formatMetricValue(value: number, format: string, unit: string | null): string {
    switch (format) {
        case 'percentage':
            return `${groupThousands(value, 1)}%`
        case 'percentage_scaled':
            return `${groupThousands(value * 100, 1)}%`
        case 'duration': {
            const seconds = unit === 'ms' ? value / 1000 : value
            if (unit === 'ms' && value < 1000) {
                return `${groupThousands(value)} ms`
            }
            return seconds >= 60 ? `${groupThousands(seconds / 60, 1)} min` : `${groupThousands(seconds, 1)}s`
        }
        case 'currency': {
            const code = (unit ?? '').toUpperCase()
            const symbol = CURRENCY_SYMBOLS[code]
            return symbol ? `${symbol}${compactAmount(value)}` : `${compactAmount(value)}${code ? ` ${code}` : ''}`
        }
        default: {
            const number = groupThousands(value, Number.isInteger(value) ? 0 : 1)
            return unit ? `${number} ${unit}` : number
        }
    }
}

export function primaryMetric<T extends MetricInput>(metrics: readonly T[]): T | undefined {
    return metrics.find((metric) => metric.role === 'primary' && metric.value !== null)
}

// Live metrics and charts. Ported from the web inbox: `utils/reportMetrics.ts`, `utils/reportChartQuery.ts` and
// `utils/chartOpenTarget.ts` in `products/signals/frontend/inbox/`.

type JsonRecord = Record<string, unknown>

export interface TrendsInsight extends JsonRecord {
    kind: 'InsightVizNode'
    source: JsonRecord & { kind: 'TrendsQuery' }
}

export function asTrendsInsight(query: unknown): TrendsInsight | undefined {
    const node = asRecord(query)
    const source = asRecord(node?.source)
    return node?.kind === 'InsightVizNode' && source?.kind === 'TrendsQuery' ? (node as TrendsInsight) : undefined
}

const VALUE_FORMATS: ReadonlySet<string> = new Set<MetricValueFormat>([
    'number',
    'count',
    'percentage',
    'percentage_scaled',
    'duration',
    'currency',
])

export function metricValueFormat(value: unknown): MetricValueFormat {
    return typeof value === 'string' && VALUE_FORMATS.has(value) ? (value as MetricValueFormat) : 'number'
}

const INTERVALS: ReadonlySet<string> = new Set<MetricInterval>(['hour', 'day', 'week', 'month'])

export function trendsInterval(trendsQuery: unknown): MetricInterval {
    const interval = asRecord(trendsQuery)?.interval
    return typeof interval === 'string' && INTERVALS.has(interval) ? (interval as MetricInterval) : 'day'
}

export function metricInterval(insight: TrendsInsight | undefined): MetricInterval {
    return trendsInterval(insight?.source)
}

function seriesNodes(insight: TrendsInsight): JsonRecord[] {
    return Array.isArray(insight.source.series) ? insight.source.series.filter(isRecord) : []
}

/**
 * Bars for a metric whose buckets add up (a count, or revenue summed per bucket), a line for a level (a rate, a
 * duration, an average). Bars invite the reader to add the buckets up, which misreads a rate.
 */
export function metricChartKind(valueFormat: MetricValueFormat, insight: TrendsInsight | undefined): MetricChartKind {
    if (valueFormat === 'count') {
        return 'bar'
    }
    if (valueFormat === 'currency') {
        const maths = insight ? seriesNodes(insight).map((series) => series.math) : []
        return maths.length > 0 && maths.every((math) => math === 'sum') ? 'bar' : 'line'
    }
    return 'line'
}

function withDisplay(insight: TrendsInsight, display: string, resetView: boolean): JsonRecord {
    const trendsFilter: JsonRecord = { ...asRecord(insight.source.trendsFilter), display }
    if (resetView) {
        // One series is drawn, so a stored percent-stack view would flatten every bucket to 100% and a hidden
        // legend index could hide the only series.
        trendsFilter.showPercentStackView = false
        delete trendsFilter.hiddenLegendIndexes
    }
    return { ...insight.source, kind: 'TrendsQuery', trendsFilter }
}

export function metricSeriesQuery(insight: TrendsInsight, chart: MetricChartKind): JsonRecord {
    return withDisplay(insight, chart === 'bar' ? 'ActionsBar' : 'ActionsLineGraph', true)
}

/**
 * The `TrendsQuery` for the one number over the whole window. The server aggregates it, which matters for distinct
 * users: summing the buckets would count a returning person once per bucket.
 */
export function metricAggregateQuery(insight: TrendsInsight): JsonRecord {
    return withDisplay(insight, 'BoldNumber', false)
}

const RELATIVE_WINDOW = /^-(\d+)([hdwmy])$/
const WINDOW_NOUNS: Record<string, string> = { h: 'hour', d: 'day', w: 'week', m: 'month', y: 'year' }
export const CURRENT_WINDOW_LABEL = 'Current window'

/** "Last 14 days" for a relative `date_from`, as the web labels it. */
export function metricWindowLabel(insight: TrendsInsight | undefined): string {
    const dateFrom = asRecord(insight?.source.dateRange)?.date_from
    const match = typeof dateFrom === 'string' ? RELATIVE_WINDOW.exec(dateFrom) : null
    const noun = match?.[2] ? WINDOW_NOUNS[match[2]] : undefined
    if (!match || !noun) {
        return CURRENT_WINDOW_LABEL
    }
    const amount = Number(match[1])
    return amount === 1 ? `Last ${noun}` : `Last ${amount} ${noun}s`
}

function countPropertyFilters(properties: unknown): number {
    if (Array.isArray(properties)) {
        return properties.reduce<number>((count, item) => count + countPropertyFilters(item), 0)
    }
    const node = asRecord(properties)
    if (!node) {
        return 0
    }
    // A property group nests its filters under `values`; a leaf filter has a `key`.
    if (Array.isArray(node.values)) {
        return countPropertyFilters(node.values)
    }
    return typeof node.key === 'string' ? 1 : 0
}

export function metricFilterCount(insight: TrendsInsight | undefined): number {
    if (!insight) {
        return 0
    }
    const inSeries = seriesNodes(insight).reduce((count, series) => count + countPropertyFilters(series.properties), 0)
    return inSeries + countPropertyFilters(insight.source.properties)
}

// nginx refuses a request line over 8 KiB by default, so a longer link would open on an error page.
export const MAX_OPEN_URL_LENGTH = 8000

// The insight scene honors these, so a link that kept them would open an insight with no filter bar.
const EMBED_FLAGS = [
    'full',
    'embedded',
    'showFilters',
    'showHeader',
    'showTable',
    'showCorrelationTable',
    'showResults',
]

function withoutEmbedFlags(node: JsonRecord): JsonRecord {
    const copy = { ...node }
    for (const key of EMBED_FLAGS) {
        delete copy[key]
    }
    return copy
}

export function insightOpenUrl(scope: ProjectScope, query: unknown): string | undefined {
    const node = asRecord(query)
    if (!node) {
        return undefined
    }
    const base = `${scope.host}/project/${scope.projectId}`
    if (node.kind === 'SavedInsightNode') {
        return typeof node.shortId === 'string' && node.shortId
            ? `${base}/insights/${encodeURIComponent(node.shortId)}`
            : undefined
    }
    const json = encodeURIComponent(JSON.stringify(withoutEmbedFlags(node)))
    const url =
        node.kind === 'DataVisualizationNode' && asRecord(node.source)?.kind === 'HogQLQuery'
            ? `${base}/sql?open_query=${json}`
            : `${base}/insights/new#q=${json}`
    return url.length > MAX_OPEN_URL_LENGTH ? undefined : url
}

function finite(value: unknown): number | undefined {
    return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function firstTrendsResult(response: unknown): JsonRecord | undefined {
    const body = asRecord(response)
    const results = Array.isArray(body?.result) ? body.result : Array.isArray(body?.results) ? body.results : undefined
    return asRecord(results?.[0])
}

/** The first series' buckets. Days and values are zipped to the shorter list; a bucket with no number is NaN. */
export function trendsSeries(response: unknown, interval: MetricInterval): MetricSeries | undefined {
    const first = firstTrendsResult(response)
    if (!Array.isArray(first?.days) || !Array.isArray(first.data)) {
        return undefined
    }
    const days = first.days.filter((day): day is string => typeof day === 'string')
    const length = Math.min(days.length, first.data.length)
    if (length === 0) {
        return undefined
    }
    const data = first.data
    return {
        interval,
        points: days.slice(0, length).map((at, index) => ({ at, value: finite(data[index]) ?? Number.NaN })),
    }
}

/** The server's total for the window, from a `BoldNumber` response. Never a sum of buckets. */
export function trendsAggregate(response: unknown): number | undefined {
    return finite(firstTrendsResult(response)?.aggregated_value)
}

function snapshotOf(metric: ReportMetricApi): MetricSnapshot | undefined {
    const value = finite(metric.value)
    if (value === undefined) {
        return undefined
    }
    return {
        value,
        at: metric.value_at ?? null,
        series: (metric.series ?? []).filter((point) => Number.isFinite(point)),
    }
}

function captionOf(caption: string | null | undefined): string | undefined {
    const trimmed = caption?.trim()
    return trimmed ? trimmed : undefined
}

/** A metric with no query (redacted, or a list response) keeps its snapshot and gets `data: none`. */
export function metricView(metric: ReportMetricApi, scope: ProjectScope): MetricView {
    const insight = asTrendsInsight(metric.query)
    const format: MetricFormat = { valueFormat: metricValueFormat(metric.value_format), unit: metric.unit ?? null }
    const chart = metricChartKind(format.valueFormat, insight)
    const data: MetricData = insight
        ? {
              kind: 'query',
              seriesQuery: metricSeriesQuery(insight, chart),
              aggregateQuery: metricAggregateQuery(insight),
          }
        : { kind: 'none' }
    const caption = captionOf(metric.caption)
    const snapshot = snapshotOf(metric)
    const openUrl = insight ? insightOpenUrl(scope, insight) : undefined
    return {
        metricId: metric.metric_id,
        role: metric.role === 'primary' ? 'primary' : 'supporting',
        title: metric.title,
        ...(caption ? { caption } : {}),
        format,
        chart,
        interval: metricInterval(insight),
        ...(snapshot ? { snapshot } : {}),
        data,
        windowLabel: metricWindowLabel(insight),
        filterCount: metricFilterCount(insight),
        ...(openUrl ? { openUrl } : {}),
    }
}

// Trends displays that draw buckets over time. Pie, bold number, table, world map and value bars aggregate the
// window away, so the app cannot draw them.
const LINE_DISPLAYS: ReadonlySet<string> = new Set([
    'ActionsLineGraph',
    'ActionsLineGraphCumulative',
    'ActionsAreaGraph',
])
const BAR_DISPLAYS: ReadonlySet<string> = new Set(['ActionsBar', 'ActionsStackedBar', 'ActionsUnstackedBar'])

/** The chart kind of a trends display that draws buckets over time, whatever its series and breakdowns. */
export function timeSeriesChartKind(insight: TrendsInsight | undefined): MetricChartKind | undefined {
    if (!insight) {
        return undefined
    }
    const display = asRecord(insight.source.trendsFilter)?.display
    if (display === undefined || display === null || (typeof display === 'string' && LINE_DISPLAYS.has(display))) {
        return 'line'
    }
    return typeof display === 'string' && BAR_DISPLAYS.has(display) ? 'bar' : undefined
}

// Distinct-user math counts a person once per bucket or breakdown value, so a sum counts the same people again. Only
// these maths add up.
const SUMMABLE_MATH: ReadonlySet<unknown> = new Set([
    undefined,
    null,
    'total',
    'sum',
    'first_time_for_user',
    'first_matching_event_for_user',
])

export function isSummableMath(math: unknown): boolean {
    return SUMMABLE_MATH.has(math)
}

/** A breakdown by one property (`breakdown`) or by several (`breakdowns`). */
export function hasBreakdown(source: unknown): boolean {
    const filter = asRecord(asRecord(source)?.breakdownFilter)
    return Boolean(filter?.breakdown) || (Array.isArray(filter?.breakdowns) && filter.breakdowns.length > 0)
}

/** The chart kind when the app can draw the chart, else undefined. The app draws one series without a breakdown. */
export function drawableChartKind(insight: TrendsInsight | undefined): MetricChartKind | undefined {
    if (!insight || seriesNodes(insight).length !== 1 || hasBreakdown(insight.source)) {
        return undefined
    }
    return timeSeriesChartKind(insight)
}

/** Keeps the authored display, such as a cumulative line, which the server computes. */
function chartSeriesQuery(insight: TrendsInsight, kind: MetricChartKind): JsonRecord {
    const display = asRecord(insight.source.trendsFilter)?.display
    const fallback = kind === 'bar' ? 'ActionsBar' : 'ActionsLineGraph'
    return withDisplay(insight, typeof display === 'string' ? display : fallback, true)
}

const AXIS_FORMATS: Record<string, MetricFormat> = {
    percentage: { valueFormat: 'percentage', unit: null },
    percentage_scaled: { valueFormat: 'percentage_scaled', unit: null },
    duration: { valueFormat: 'duration', unit: 's' },
    duration_ms: { valueFormat: 'duration', unit: 'ms' },
}

export function chartFormat(insight: TrendsInsight | undefined): MetricFormat {
    const axis = asRecord(insight?.source.trendsFilter)?.aggregationAxisFormat
    return (typeof axis === 'string' ? AXIS_FORMATS[axis] : undefined) ?? { valueFormat: 'number', unit: null }
}

/** A chart the app cannot draw keeps its title and a link to the web, with no `data`. */
export function reportChartView(chart: ReportChartApi, scope: ProjectScope): ReportChartView {
    const insight = asTrendsInsight(chart.query)
    const kind = drawableChartKind(insight)
    const caption = captionOf(chart.caption)
    const openUrl = insightOpenUrl(scope, chart.query)
    return {
        chartId: chart.chart_id,
        title: chart.title,
        ...(caption ? { caption } : {}),
        ...(insight && kind
            ? {
                  data: {
                      kind: 'query' as const,
                      seriesQuery: chartSeriesQuery(insight, kind),
                      aggregateQuery: metricAggregateQuery(insight),
                  },
              }
            : {}),
        format: chartFormat(insight),
        chart: kind ?? 'line',
        interval: metricInterval(insight),
        ...(openUrl ? { openUrl } : {}),
    }
}
