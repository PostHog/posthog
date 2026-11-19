import { asRecord, isRecord } from '@/lib/records'
import { plural } from '@/model/adapters/text'
import type { MetricInterval } from '@/model/types'
import type { InsightSnapshot } from '@/model/views'
import { formatClockTime } from '@/ui/chart/chartMath'
import { seriesColor } from '@/ui/chart/palette'
import { sqlRowsText } from '@/ui/chart/sqlCellFormat'
import { rangeLabel } from '../rangePresets'
import { intervalLabel, previousRangeText, resolvedRangeText } from '../snapshotChart'

// Every field comes from the insight response the screen already holds (`GET insights/{id}/`, or the same insight
// inline in a dashboard tile), so opening the sheet sends no request.

type JsonRecord = Record<string, unknown>

export interface AboutRow {
    label: string
    values: string[]
    /** Event names, filters and SQL show in the mono chip style. */
    mono: boolean
}

export interface AboutSeries {
    key: string
    label: string
    color: string
    rows: AboutRow[]
}

export interface AboutContent {
    name: string
    description: string | null
    series: AboutSeries[]
    formula: string | null
    sql: string | null
    /** A SQL insight's result size, such as "First 100 rows, 3 columns". */
    sqlResult: string | null
    breakdown: string
    filters: string[]
    testAccounts: string
    range: string
    interval: string | null
    compare: string
    computed: string | null
    inProgressNote: string | null
    createdBy: string | null
}

const MATH_LABELS: Record<string, string> = {
    total: 'Total count',
    dau: 'Unique users',
    weekly_active: 'Weekly active users',
    monthly_active: 'Monthly active users',
    unique_session: 'Unique sessions',
    unique_group: 'Unique groups',
    first_time_for_user: 'First time for a user',
    first_matching_event_for_user: 'First matching event for a user',
    hogql: 'SQL expression',
}

const PROPERTY_MATH_LABELS: Record<string, string> = {
    sum: 'Sum',
    avg: 'Average',
    min: 'Minimum',
    max: 'Maximum',
    median: 'Median',
    p75: '75th percentile',
    p90: '90th percentile',
    p95: '95th percentile',
    p99: '99th percentile',
}

const OPERATOR_LABELS: Record<string, string> = {
    exact: '=',
    is_not: '≠',
    icontains: 'contains',
    not_icontains: "doesn't contain",
    regex: 'matches',
    not_regex: "doesn't match",
    gt: '>',
    gte: '≥',
    lt: '<',
    lte: '≤',
    is_date_before: 'before',
    is_date_after: 'after',
    is_date_exact: 'on',
    between: 'between',
    not_between: 'not between',
    in: 'in',
    not_in: 'not in',
}

const NO_VALUE_OPERATORS: Record<string, string> = { is_set: 'is set', is_not_set: 'is not set' }

function text(value: unknown): string | null {
    return typeof value === 'string' && value.trim() ? value.trim() : null
}

function sourceOf(query: unknown): JsonRecord {
    const node = asRecord(query)
    return asRecord(node?.source) ?? node ?? {}
}

function valueText(value: unknown): string {
    if (Array.isArray(value)) {
        return value.map(valueText).join(', ')
    }
    if (value === null || value === undefined) {
        return ''
    }
    return String(value)
}

/** One property filter as the web's filter pill reads it, such as "$host = app.example.com". */
export function filterLabel(filter: JsonRecord): string {
    if (filter.type === 'cohort') {
        return `In cohort ${valueText(filter.cohort_name ?? filter.value)}`
    }
    if (filter.type === 'hogql') {
        return valueText(filter.key)
    }
    const key = valueText(filter.label ?? filter.key)
    const operator = typeof filter.operator === 'string' ? filter.operator : 'exact'
    const noValue = NO_VALUE_OPERATORS[operator]
    if (noValue) {
        return `${key} ${noValue}`
    }
    return `${key} ${OPERATOR_LABELS[operator] ?? operator} ${valueText(filter.value)}`.trim()
}

/** Property filters arrive as a list or as nested AND / OR groups. The sheet lists the leaves. */
export function flattenFilters(properties: unknown): JsonRecord[] {
    if (Array.isArray(properties)) {
        return properties
            .filter(isRecord)
            .flatMap((entry) => (Array.isArray(entry.values) ? flattenFilters(entry.values) : [entry]))
    }
    const group = asRecord(properties)
    return group && Array.isArray(group.values) ? flattenFilters(group.values) : []
}

function mathLabel(node: JsonRecord): string {
    const math = typeof node.math === 'string' ? node.math : 'total'
    const property = text(node.math_property) ?? text(node.math_hogql)
    const propertyMath = PROPERTY_MATH_LABELS[math]
    if (propertyMath) {
        return property ? `${propertyMath} of ${property}` : propertyMath
    }
    if (math === 'hogql' && property) {
        return property
    }
    return MATH_LABELS[math] ?? math
}

function seriesRows(node: JsonRecord): AboutRow[] {
    const rows: AboutRow[] = []
    if (node.kind === 'ActionsNode') {
        rows.push({ label: 'Action', values: [text(node.name) ?? `Action ${valueText(node.id)}`], mono: false })
    } else if (node.kind === 'DataWarehouseNode') {
        rows.push({ label: 'Table', values: [text(node.table_name) ?? 'Data warehouse table'], mono: true })
    } else {
        rows.push({ label: 'Event', values: [text(node.event) ?? 'All events'], mono: true })
    }
    rows.push({ label: 'Math', values: [mathLabel(node)], mono: false })
    const filters = flattenFilters(node.properties).map(filterLabel)
    if (filters.length > 0) {
        rows.push({ label: 'Filters', values: filters, mono: true })
    }
    return rows
}

function seriesName(node: JsonRecord, index: number): string {
    return text(node.custom_name) ?? text(node.name) ?? text(node.event) ?? `Series ${index + 1}`
}

function formulaOf(source: JsonRecord): string | null {
    const filter = asRecord(source.trendsFilter)
    const formula = text(filter?.formula)
    if (formula) {
        return formula
    }
    const nodes = Array.isArray(filter?.formulaNodes) ? filter.formulaNodes.filter(isRecord) : []
    const formulas = nodes.flatMap((node) => {
        const value = text(node.formula)
        return value ? [value] : []
    })
    return formulas.length > 0 ? formulas.join(', ') : null
}

function breakdownOf(source: JsonRecord): string {
    const filter = asRecord(source.breakdownFilter)
    const many = Array.isArray(filter?.breakdowns) ? filter.breakdowns.filter(isRecord) : []
    if (many.length > 0) {
        return many.map((entry) => valueText(entry.property)).join(', ')
    }
    const single = filter?.breakdown
    if (single === null || single === undefined || single === '') {
        return 'None'
    }
    return valueText(single)
}

function ageText(ageMs: number): string {
    const minutes = Math.floor(ageMs / 60_000)
    if (minutes < 1) {
        return 'Just now'
    }
    if (minutes < 60) {
        return `${minutes} min ago`
    }
    const hours = Math.floor(minutes / 60)
    if (hours < 24) {
        return `${hours} h ago`
    }
    const days = Math.floor(hours / 24)
    return days === 1 ? '1 day ago' : `${days} days ago`
}

const UNIT_NOUNS: Record<MetricInterval, string> = { hour: 'hour', day: 'day', week: 'week', month: 'month' }

function createdByText(snapshot: InsightSnapshot): string | null {
    if (!snapshot.createdBy) {
        return null
    }
    const created = snapshot.createdAt ? new Date(snapshot.createdAt) : null
    if (!created || Number.isNaN(created.getTime())) {
        return snapshot.createdBy
    }
    const date = created.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
    return `${snapshot.createdBy} on ${date}`
}

/** `palette` is the theme's `chartPalette`, so each series row matches its line on the chart. */
export function aboutContent(snapshot: InsightSnapshot, now: number, palette: readonly string[]): AboutContent {
    const source = sourceOf(snapshot.query)
    const kind = typeof source.kind === 'string' ? source.kind : null
    const nodes = Array.isArray(source.series) ? source.series.filter(isRecord) : []
    const resolved = resolvedRangeText(snapshot.resolvedRange, snapshot.interval)
    const saved = rangeLabel(null, snapshot.savedRange)
    const range = resolved ? `${resolved}${snapshot.timezone ? `, ${snapshot.timezone}` : ''}` : (saved ?? 'As saved')
    const comparing = asRecord(source.compareFilter)?.compare === true
    const previous = comparing ? previousRangeText(snapshot) : null
    const lastRefresh = snapshot.lastRefreshAt ? Date.parse(snapshot.lastRefreshAt) : Number.NaN
    const unit = UNIT_NOUNS[snapshot.interval]
    return {
        name: snapshot.name,
        description: snapshot.description,
        series: nodes.map((node, index) => ({
            key: `${index}`,
            label: seriesName(node, index),
            color: seriesColor(index, palette),
            rows: seriesRows(node),
        })),
        formula: formulaOf(source),
        sql: kind === 'HogQLQuery' ? text(source.query) : null,
        sqlResult: snapshot.sqlTable
            ? `${sqlRowsText(snapshot.sqlTable)}, ${plural(snapshot.sqlTable.columns.length, 'column')}`
            : null,
        breakdown: breakdownOf(source),
        filters: flattenFilters(source.properties).map(filterLabel),
        testAccounts: source.filterTestAccounts === true ? 'Filtered out' : 'Included',
        range,
        interval: typeof source.interval === 'string' ? intervalLabel(snapshot.interval) : null,
        compare: comparing ? (previous ? `Compared with ${previous}` : 'Compared with the previous period') : 'Off',
        computed: Number.isFinite(lastRefresh) ? ageText(Math.max(0, now - lastRefresh)) : null,
        inProgressNote:
            snapshot.inProgressFrom && Number.isFinite(lastRefresh)
                ? `The last ${unit} is still in progress. It has data until ${formatClockTime(lastRefresh)} and draws as a dashed line.`
                : null,
        createdBy: createdByText(snapshot),
    }
}
