import type { InsightApi, QueryStatusFieldsApi, UserBasicApi } from '@/api/insights'
import { parseBucketStart } from '@/lib/dates'
import { asRecord, isRecord } from '@/lib/records'

import type { MetricFormat, MetricInterval, MetricPoint, MetricSeries } from '../types'
import type {
    InsightCapabilities,
    InsightSeriesView,
    InsightSnapshot,
    NumberDelta,
    ResolvedRange,
    SavedRange,
    SqlTableView,
} from '../views'
import { displaySeriesLabel, rankingView } from './breakdown'
import { funnelView } from './funnel'
import { insightValueFormat } from './insightFormatting'
import { asTrendsInsight, hasBreakdown, isSummableMath, timeSeriesChartKind, trendsInterval } from './metric'
import { retentionView } from './retention'
import {
    effectiveSqlDisplay,
    hasSqlChartSeries,
    sqlCellNumber,
    sqlChartKind,
    sqlInterval,
    sqlQueryDisplay,
    sqlRankingView,
    sqlResultDisplay,
    sqlSeriesViews,
    sqlTableView,
} from './sqlVisualization'

type JsonRecord = Record<string, unknown>

export interface SnapshotContext {
    /** Device ms of this response. */
    readAt: number
    /** Server ms now, to find the bucket that is still in progress. */
    serverNow: number
    /** The tile's `filters_overrides`, for "Uses its own range". */
    tileOverrides?: Record<string, unknown> | null
    /** Known from the dashboard read. A per-tile read returns the insight without the tile's overrides. */
    usesOwnRange?: boolean
}

interface ResponseStatus {
    result?: unknown
    results?: unknown
    query_status?: QueryStatusFieldsApi | null
}

/**
 * Only a response with a result and no error may set freshness or data. A rate-limited insight response answers 200
 * with `result: null` and `last_refresh` set to now, so trusting it would claim "Updated just now" for old numbers.
 */
export function hasGoodResult(response: ResponseStatus): boolean {
    const result = response.result !== undefined ? response.result : response.results
    return result !== null && result !== undefined && !response.query_status?.error
}

export function isRateLimited(response: ResponseStatus): boolean {
    return response.query_status?.error_code === 'rate_limited'
}

function finite(value: unknown): number | undefined {
    return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function sourceOf(query: unknown): JsonRecord | undefined {
    const node = asRecord(query)
    return asRecord(node?.source) ?? node
}

export function queryKindOf(query: unknown): string | null {
    const source = sourceOf(query)
    return typeof source?.kind === 'string' ? source.kind : null
}

function sqlText(query: unknown): string | null {
    const source = sourceOf(query)
    return source?.kind === 'HogQLQuery' && typeof source.query === 'string' ? source.query : null
}

// The web's test in `frontend/src/scenes/insights/SqlInsightFilters.tsx`.
const FILTERS_PLACEHOLDER = /\{\s*filters\b/

/** A SQL insight without `{filters}` ignores dashboard filters, so a range override only changes its cache key. */
export function ignoresRangeOverride(query: unknown): boolean {
    const sql = sqlText(query)
    return sql !== null && !FILTERS_PLACEHOLDER.test(sql)
}

/** True for a tile that keeps its own dates when the dashboard range changes. */
export function usesOwnRange(tileOverrides: Record<string, unknown> | null | undefined, query: unknown): boolean {
    const overrides = tileOverrides ?? {}
    if (overrides.date_from || overrides.date_to || overrides.ignoreDashboardFilters) {
        return true
    }
    return ignoresRangeOverride(query)
}

export function savedRangeOf(query: unknown): SavedRange {
    const source = sourceOf(query)
    const range = asRecord(source?.dateRange) ?? asRecord(asRecord(source?.filters)?.dateRange)
    return {
        dateFrom: typeof range?.date_from === 'string' ? range.date_from : null,
        dateTo: typeof range?.date_to === 'string' ? range.date_to : null,
    }
}

function displayOf(query: unknown): string | null {
    const node = asRecord(query)
    const source = sourceOf(query)
    const display = asRecord(source?.trendsFilter)?.display ?? node?.display
    return typeof display === 'string' ? display : null
}

const KIND_LABELS: Record<string, string> = {
    FunnelsQuery: 'Funnel',
    RetentionQuery: 'Retention',
    PathsQuery: 'Paths',
    StickinessQuery: 'Stickiness',
    LifecycleQuery: 'Lifecycle',
    HogQLQuery: 'SQL',
}

const TRENDS_DISPLAY_LABELS: Record<string, string> = {
    BoldNumber: 'Big number',
    ActionsPie: 'Pie',
    ActionsTable: 'Table',
    WorldMap: 'Map',
    ActionsBarValue: 'Bar',
}

const SQL_DISPLAY_LABELS: Record<string, string> = {
    BoldNumber: 'Big number',
    ActionsTable: 'Table',
    ActionsLineGraph: 'Line',
    ActionsLineGraphCumulative: 'Line',
    ActionsAreaGraph: 'Line',
    ActionsBar: 'Bar',
    ActionsStackedBar: 'Bar',
    ActionsUnstackedBar: 'Bar',
    ActionsBarValue: 'Bar',
    ActionsProportionBar: 'Bar',
    ActionsPie: 'Pie',
    ActionsDonut: 'Pie',
}

/** With a SQL result, the label names the display that Auto resolves to. */
export function kindLabelOf(query: unknown, sqlTable: SqlTableView | null = null): string {
    const kind = queryKindOf(query)
    if (kind === 'HogQLQuery') {
        const display = effectiveSqlDisplay(query, sqlTable)
        return (display ? SQL_DISPLAY_LABELS[display] : undefined) ?? 'SQL'
    }
    const display = displayOf(query)
    if (display === 'BoldNumber') {
        return 'Big number'
    }
    if (kind === 'TrendsQuery') {
        const drawable = timeSeriesChartKind(asTrendsInsight(query))
        if (drawable) {
            return drawable === 'bar' ? 'Bar' : 'Line'
        }
        return (display ? TRENDS_DISPLAY_LABELS[display] : undefined) ?? 'Chart'
    }
    return (kind ? KIND_LABELS[kind] : undefined) ?? 'Insight'
}

function seriesNodes(query: unknown): JsonRecord[] {
    const series = sourceOf(query)?.series
    return Array.isArray(series) ? series.filter(isRecord) : []
}

const PEOPLE_NODE_KINDS: ReadonlySet<string> = new Set(['EventsNode', 'ActionsNode'])

function hasFormula(query: unknown): boolean {
    const filter = asRecord(sourceOf(query)?.trendsFilter)
    return Boolean(filter?.formula) || (Array.isArray(filter?.formulaNodes) && filter.formulaNodes.length > 0)
}

/** "View people" needs a trends series of events or actions with people behind it: no formula and no SQL math. */
function canShowPeople(query: unknown): boolean {
    if (queryKindOf(query) !== 'TrendsQuery' || hasFormula(query) || asRecord(query)?.hidePersonsModal) {
        return false
    }
    const nodes = seriesNodes(query)
    return (
        nodes.length > 0 &&
        nodes.every(
            (node) => typeof node.kind === 'string' && PEOPLE_NODE_KINDS.has(node.kind) && node.math !== 'hogql'
        )
    )
}

/** The series count and breakdown of a trends insight, so "Choose tile" can say why a tile is out. */
export function tileShapeOf(query: unknown): { seriesCount: number; hasBreakdown: boolean } {
    if (queryKindOf(query) !== 'TrendsQuery') {
        return { seriesCount: 0, hasBreakdown: false }
    }
    return { seriesCount: seriesNodes(query).length, hasBreakdown: hasBreakdown(sourceOf(query)) }
}

function trendsEntries(result: unknown): JsonRecord[] {
    return Array.isArray(result) ? result.filter(isRecord) : []
}

/**
 * Number: a big number, or a trends insight with one series or one result (a formula), and no breakdown. With several
 * series or breakdown values the first one would stand for the whole insight. Chart: a drawable trends series, or a
 * SQL chart over time. Without its result, a SQL insight on Auto has neither.
 */
export function capabilitiesOf(
    query: unknown,
    result?: unknown,
    sqlTable: SqlTableView | null = null
): InsightCapabilities {
    const kind = queryKindOf(query)
    if (kind === 'HogQLQuery') {
        const display = sqlTable ? sqlResultDisplay(query, sqlTable) : sqlQueryDisplay(query)
        const chart = display === 'chart' && (!sqlTable || hasSqlChartSeries(query, sqlTable))
        return { number: display === 'number', chart, people: false }
    }
    const display = displayOf(query)
    const chart = kind === 'TrendsQuery' && timeSeriesChartKind(asTrendsInsight(query)) !== undefined
    let number = false
    if (kind === 'TrendsQuery') {
        const current = trendsEntries(result).filter((entry) => compareOf(entry) !== 'previous')
        number =
            display === 'BoldNumber' ||
            (!hasBreakdown(sourceOf(query)) && (seriesNodes(query).length === 1 || current.length === 1))
    }
    return { number, chart, people: canShowPeople(query) }
}

function pointsOf(entry: JsonRecord | undefined): MetricPoint[] {
    if (!entry || !Array.isArray(entry.days) || !Array.isArray(entry.data)) {
        return []
    }
    const data = entry.data
    const days = entry.days.filter((day): day is string => typeof day === 'string')
    const length = Math.min(days.length, data.length)
    return days.slice(0, length).map((at, index) => ({ at, value: finite(data[index]) ?? Number.NaN }))
}

function seriesIndexOf(entry: JsonRecord, fallback: number): number {
    return finite(asRecord(entry.action)?.order) ?? fallback
}

function breakdownOf(entry: JsonRecord): InsightSeriesView['breakdownValue'] {
    const value = entry.breakdown_value
    if (
        Array.isArray(value) &&
        value.every((part) => part === null || typeof part === 'string' || typeof part === 'number')
    ) {
        return value
    }
    return typeof value === 'string' || typeof value === 'number' ? value : null
}

function seriesIdentity(
    seriesIndex: number,
    breakdownValue: InsightSeriesView['breakdownValue'],
    compare: string | null
): string {
    return JSON.stringify([seriesIndex, breakdownValue, compare])
}

function compareOf(entry: JsonRecord): 'current' | 'previous' | null {
    return entry.compare_label === 'previous' ? 'previous' : entry.compare_label === 'current' ? 'current' : null
}

function seriesViews(entries: JsonRecord[]): InsightSeriesView[] {
    return entries.map((entry, index) => {
        const seriesIndex = seriesIndexOf(entry, index)
        const breakdownValue = breakdownOf(entry)
        const compare = compareOf(entry)
        return {
            key: seriesIdentity(seriesIndex, breakdownValue, compare),
            label: typeof entry.label === 'string' ? displaySeriesLabel(entry.label) : `Series ${seriesIndex + 1}`,
            points: pointsOf(entry),
            compare,
            seriesIndex,
            breakdownValue,
        }
    })
}

const INTERVAL_MS: Record<MetricInterval, number> = {
    hour: 3_600_000,
    day: 86_400_000,
    week: 7 * 86_400_000,
    month: 31 * 86_400_000,
}

/** The last bucket is in progress when the resolved window reaches past now. */
function inProgressFrom(
    points: MetricPoint[],
    resolved: ResolvedRange | null,
    interval: MetricInterval,
    serverNow: number
): string | null {
    const last = points[points.length - 1]
    if (!last) {
        return null
    }
    if (resolved) {
        return Date.parse(resolved.to) > serverNow ? last.at : null
    }
    return parseBucketStart(last.at) + INTERVAL_MS[interval] > serverNow ? last.at : null
}

function isSummable(query: unknown): boolean {
    return isSummableMath(seriesNodes(query)[0]?.math)
}

function makeDelta(
    value: number,
    previous: number,
    basis: NumberDelta['basis'],
    previousAt: string | null,
    format: MetricFormat
): NumberDelta {
    const change = value - previous
    const points = format.valueFormat === 'percentage' || format.valueFormat === 'percentage_scaled'
    return {
        previous,
        change: format.valueFormat === 'percentage_scaled' ? change * 100 : change,
        percent: previous === 0 ? null : (change / Math.abs(previous)) * 100,
        unit: points ? 'points' : 'percent',
        basis,
        previousAt,
    }
}

function sumFinite(points: MetricPoint[]): number | undefined {
    const values = points.map((point) => point.value).filter((value) => Number.isFinite(value))
    return values.length > 0 ? values.reduce((total, value) => total + value, 0) : undefined
}

function lastFiniteIndex(points: MetricPoint[]): number {
    for (let index = points.length - 1; index >= 0; index -= 1) {
        if (Number.isFinite(points[index]?.value)) {
            return index
        }
    }
    return -1
}

interface NumberParts {
    value: number | null
    valueAt: string | null
    delta: NumberDelta | null
}

const NO_NUMBER: NumberParts = { value: null, valueAt: null, delta: null }

/**
 * The big number and its delta, so that both always describe the same thing:
 * - a server aggregate (`aggregated_value`) is the value; the previous period's aggregate gives the delta;
 * - with a compare series and summable math, the window totals;
 * - otherwise the last complete bucket, against the same bucket of the previous period, or else the bucket before it.
 * The bucket that contains now is never complete.
 */
export function numberParts(
    query: unknown,
    entries: JsonRecord[],
    format: MetricFormat,
    inProgressAt: string | null
): NumberParts {
    const current = entries.find((entry) => compareOf(entry) !== 'previous')
    if (!current) {
        return NO_NUMBER
    }
    const previousEntry = entries.find(
        (entry) =>
            compareOf(entry) === 'previous' &&
            seriesIndexOf(entry, 0) === seriesIndexOf(current, 0) &&
            seriesIdentity(seriesIndexOf(entry, 0), breakdownOf(entry), null) ===
                seriesIdentity(seriesIndexOf(current, 0), breakdownOf(current), null)
    )
    const aggregate = finite(current.aggregated_value)
    if (aggregate !== undefined) {
        const previousAggregate = finite(previousEntry?.aggregated_value)
        return {
            value: aggregate,
            valueAt: null,
            delta:
                previousAggregate === undefined
                    ? null
                    : makeDelta(aggregate, previousAggregate, 'compare', null, format),
        }
    }
    const points = pointsOf(current)
    const previousPoints = pointsOf(previousEntry)
    if (previousEntry && isSummable(query)) {
        const total = sumFinite(points)
        const previousTotal = sumFinite(previousPoints)
        if (total === undefined) {
            return NO_NUMBER
        }
        return {
            value: total,
            valueAt: null,
            delta: previousTotal === undefined ? null : makeDelta(total, previousTotal, 'compare', null, format),
        }
    }
    const complete =
        inProgressAt !== null && points[points.length - 1]?.at === inProgressAt ? points.slice(0, -1) : points
    const index = lastFiniteIndex(complete)
    const point = complete[index]
    if (!point) {
        return NO_NUMBER
    }
    const against = previousEntry ? previousPoints[index] : complete[index - 1]
    const delta =
        against && Number.isFinite(against.value)
            ? makeDelta(point.value, against.value, previousEntry ? 'compare' : 'previous_bucket', against.at, format)
            : null
    return { value: point.value, valueAt: point.at, delta }
}

function sqlNumber(result: unknown): number | null {
    const firstRow = Array.isArray(result) ? result[0] : undefined
    return sqlCellNumber(Array.isArray(firstRow) ? firstRow[0] : undefined) ?? null
}

function userName(user: UserBasicApi | null | undefined): string | null {
    const name = [user?.first_name, user?.last_name].filter(Boolean).join(' ').trim()
    return name || user?.email || null
}

function resolvedRangeOf(response: InsightApi): ResolvedRange | null {
    const range = response.resolved_date_range
    return range?.date_from && range.date_to ? { from: range.date_from, to: range.date_to } : null
}

/**
 * Builds the snapshot of one insight read. Names and the query come from every response. Data and freshness come
 * only from a response with a result and no error; otherwise the previous values stay and `readAt` moves on. An
 * error marks the snapshot failed; a cache miss without an error keeps the previous state.
 */
export function insightSnapshot(
    response: InsightApi,
    previous: InsightSnapshot | undefined,
    context: SnapshotContext
): InsightSnapshot {
    const query = response.query
    const good = hasGoodResult(response)
    const sqlTable = good ? sqlTableView(query, response) : (previous?.sqlTable ?? null)
    const metadata = {
        insightId: response.id,
        shortId: response.short_id,
        name: response.name || response.derived_name || 'Untitled',
        description: response.description || null,
        queryKind: queryKindOf(query),
        query,
        savedRange: savedRangeOf(query),
        usesOwnRange: context.usesOwnRange ?? usesOwnRange(context.tileOverrides, query),
        kindLabel: kindLabelOf(query, sqlTable),
        // A response without an author, such as a compare read, keeps the last known one.
        createdBy: userName(response.created_by) ?? previous?.createdBy ?? null,
        createdAt: response.created_at ?? previous?.createdAt ?? null,
    }
    const isSql = metadata.queryKind === 'HogQLQuery'
    if (!good) {
        const failed = Boolean(response.query_status?.error)
        if (previous) {
            return { ...previous, ...metadata, readAt: context.readAt, refreshFailed: failed || previous.refreshFailed }
        }
        return {
            ...metadata,
            lastRefreshAt: null,
            cacheTargetAge: null,
            nextAllowedRefreshAt: null,
            readAt: context.readAt,
            refreshFailed: failed,
            resolvedRange: null,
            timezone: response.timezone ?? null,
            interval: trendsInterval(sourceOf(query)),
            format: insightValueFormat(query, response.columns, response.types),
            value: null,
            valueAt: null,
            previous: null,
            delta: null,
            series: null,
            allSeries: [],
            chartKind: isSql ? sqlChartKind(query, null) : (timeSeriesChartKind(asTrendsInsight(query)) ?? null),
            funnel: null,
            retention: null,
            ranking: null,
            sqlTable: null,
            inProgressFrom: null,
            capabilities: capabilitiesOf(query),
            computed: false,
        }
    }
    const resolvedRange = resolvedRangeOf(response)
    const isTrends = metadata.queryKind === 'TrendsQuery'
    const entries = isTrends ? trendsEntries(response.result) : []
    const allSeries = sqlTable ? sqlSeriesViews(query, sqlTable) : seriesViews(entries)
    const interval = sqlTable ? sqlInterval(allSeries[0]?.points ?? []) : trendsInterval(sourceOf(query))
    const format = insightValueFormat(query, response.columns, response.types)
    const firstCurrent = allSeries.find((series) => series.compare !== 'previous')
    // A SQL result has no resolved window to tell which bucket is still open.
    const inProgress =
        firstCurrent && !isSql ? inProgressFrom(firstCurrent.points, resolvedRange, interval, context.serverNow) : null
    const capabilities = capabilitiesOf(query, response.result, sqlTable)
    // A SQL table or chart whose first cell is a number has no big number above it.
    const sqlValue = sqlTable && sqlResultDisplay(query, sqlTable) === 'number' ? sqlNumber(response.result) : null
    const number = !isTrends
        ? { value: isSql ? sqlValue : sqlNumber(response.result), valueAt: null, delta: null }
        : capabilities.number
          ? numberParts(query, entries, format, inProgress)
          : NO_NUMBER
    const series: MetricSeries | null =
        firstCurrent && firstCurrent.points.length > 0 ? { interval, points: firstCurrent.points } : null
    return {
        ...metadata,
        lastRefreshAt: response.last_refresh,
        cacheTargetAge: response.cache_target_age,
        nextAllowedRefreshAt: response.next_allowed_client_refresh,
        readAt: context.readAt,
        refreshFailed: false,
        resolvedRange,
        timezone: response.timezone ?? null,
        interval,
        format,
        value: number.value,
        valueAt: number.valueAt,
        previous: number.delta?.previous ?? null,
        delta: number.delta,
        series,
        allSeries,
        chartKind: isSql ? sqlChartKind(query, sqlTable) : (timeSeriesChartKind(asTrendsInsight(query)) ?? null),
        funnel: funnelView(query, response.result),
        retention: retentionView(query, response.result, context.serverNow),
        ranking: sqlTable ? sqlRankingView(query, sqlTable) : rankingView(query, response.result),
        sqlTable,
        inProgressFrom: inProgress,
        capabilities,
        computed: response.is_cached === false,
    }
}

/** A failed read that never reached the server: keep the values, mark the failure. */
export function failedSnapshot<T extends { readAt: number; refreshFailed: boolean }>(previous: T, readAt: number): T {
    return { ...previous, readAt, refreshFailed: true }
}
