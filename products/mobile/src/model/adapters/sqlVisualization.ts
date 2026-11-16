import { parseBucketStart } from '@/lib/dates'
import { asRecord, isRecord } from '@/lib/records'

import type { MetricChartKind, MetricInterval, MetricPoint } from '../types'
import type {
    InsightPresentation,
    InsightSeriesView,
    RankedValueView,
    RankingView,
    SqlCell,
    SqlColumnView,
    SqlTableView,
} from '../views'

// A SQL insight is a `DataVisualizationNode` with a `HogQLQuery` source. Its result is rows of cells plus the column
// names and ClickHouse types. The rules below port `dataVisualizationLogic.ts` in
// `frontend/src/queries/nodes/DataVisualization/`, so the phone resolves the same display and axes as the web.

type JsonRecord = Record<string, unknown>

export type SqlPhoneDisplay = 'number' | 'table' | 'chart' | 'bars' | 'web'

export interface SqlResponseParts {
    result?: unknown
    columns?: unknown
    types?: unknown
    hasMore?: unknown
}

export interface SqlAxes {
    x: SqlColumnView | null
    y: SqlColumnView[]
}

// `Metric` stays on the web: it shows the latest, total or mean of the first y series by date, which is not ported.
const NUMBER_DISPLAYS: ReadonlySet<string> = new Set(['BoldNumber'])
const LINE_DISPLAYS: ReadonlySet<string> = new Set([
    'ActionsLineGraph',
    'ActionsLineGraphCumulative',
    'ActionsAreaGraph',
])
const BAR_DISPLAYS: ReadonlySet<string> = new Set(['ActionsBar', 'ActionsStackedBar', 'ActionsUnstackedBar'])
// Displays that total one value per x value. Auto category bars use the same ranking rules.
const RANKING_DISPLAYS: ReadonlySet<string> = new Set([
    'ActionsBarValue',
    'ActionsPie',
    'ActionsDonut',
    'ActionsProportionBar',
])
const NUMERICAL_SCALARS: ReadonlySet<string> = new Set(['INTEGER', 'FLOAT', 'DECIMAL'])
const DATE_SCALARS: ReadonlySet<string> = new Set(['DATE', 'DATETIME'])
// A plain decimal number. `Number()` alone would also read hex, binary and "Infinity" in a text column.
const NUMERIC_TEXT = /^\s*[-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?\s*$/i
const HOUR_MS = 3_600_000
const DAY_MS = 24 * HOUR_MS

/**
 * A cell as a number, or undefined, which a chart draws as a gap. The server's JSON writes a ClickHouse Decimal as a
 * string, and a wide integer can arrive as one too, so a numeric string counts.
 */
export function sqlCellNumber(cell: unknown): number | undefined {
    if (typeof cell === 'number') {
        return Number.isFinite(cell) ? cell : undefined
    }
    if (typeof cell === 'string' && NUMERIC_TEXT.test(cell)) {
        const parsed = Number(cell)
        return Number.isFinite(parsed) ? parsed : undefined
    }
    return undefined
}

function sourceOf(query: unknown): JsonRecord | undefined {
    return asRecord(asRecord(query)?.source)
}

export function isSqlQuery(query: unknown): boolean {
    return sourceOf(query)?.kind === 'HogQLQuery'
}

/** The saved display. Without one a SQL insight is a table, as on the web; null is `Auto`, which the result decides. */
function savedDisplay(query: unknown): string | null {
    const display = asRecord(query)?.display
    if (display === 'Auto') {
        return null
    }
    return typeof display === 'string' ? display : 'ActionsTable'
}

function chartSettingsOf(query: unknown): JsonRecord | undefined {
    return asRecord(asRecord(query)?.chartSettings)
}

function isTransposed(query: unknown): boolean {
    return asRecord(asRecord(query)?.tableSettings)?.transpose === true
}

function breakdownColumnOf(query: unknown): string | null {
    const column = chartSettingsOf(query)?.seriesBreakdownColumn
    return typeof column === 'string' && column !== '' ? column : null
}

const WRAPPER = /^(?:Nullable|LowCardinality)\((.*)\)$/

/** The ClickHouse type as the web's scalar name: `Nullable(DateTime64(6, 'UTC'))` is `DATETIME`. */
export function sqlScalar(type: string | null | undefined): string {
    if (!type) {
        return 'UNKNOWN'
    }
    let inner = type.trim()
    for (let match = WRAPPER.exec(inner); match?.[1] !== undefined; match = WRAPPER.exec(inner)) {
        inner = match[1].trim()
    }
    if (inner.startsWith('Array')) {
        return 'ARRAY'
    }
    if (inner.startsWith('Tuple')) {
        return 'TUPLE'
    }
    if (inner.startsWith('Int') || inner.startsWith('UInt')) {
        return 'INTEGER'
    }
    if (inner.startsWith('Float')) {
        return 'FLOAT'
    }
    if (inner.startsWith('Decimal')) {
        return 'DECIMAL'
    }
    if (inner === 'Bool' || inner === 'Boolean') {
        return 'BOOLEAN'
    }
    if (inner.startsWith('DateTime')) {
        return 'DATETIME'
    }
    if (inner.startsWith('Date')) {
        return 'DATE'
    }
    if (inner.includes('String')) {
        return 'STRING'
    }
    return inner
}

function decimalPlacesOf(value: unknown): number | undefined {
    return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= 100 ? value : undefined
}

function textOf(value: unknown): string {
    return typeof value === 'string' ? value : ''
}

/**
 * A SQL column's `settings.formatting`, or null without one. A percent column is a fraction scaled by 100, as the
 * web's SQL table, charts and heatmap all do, so 0.25 reads 25%.
 */
export function sqlPresentation(settings: unknown): InsightPresentation | null {
    const formatting = asRecord(asRecord(settings)?.formatting)
    if (!formatting) {
        return null
    }
    const style = typeof formatting.style === 'string' ? formatting.style : null
    return {
        kind: 'sql',
        style,
        prefix: textOf(formatting.prefix),
        suffix: textOf(formatting.suffix),
        decimalPlaces: decimalPlacesOf(formatting.decimalPlaces),
        ...(style === 'percent' ? { scale: 100 } : {}),
    }
}

function settingsFor(list: unknown, column: string): unknown {
    if (!Array.isArray(list)) {
        return undefined
    }
    return list.filter(isRecord).find((entry) => entry.column === column)?.settings
}

/**
 * The result's columns with their scalar types. A cell format comes from `tableSettings.columns`, else from the
 * matching `chartSettings.yAxis` entry, so a column without table settings reads as the chart shows it.
 */
export function sqlColumns(columns: unknown, types: unknown, query: unknown): SqlColumnView[] {
    if (!Array.isArray(columns)) {
        return []
    }
    const typeList = Array.isArray(types) ? types : []
    const tableColumns = asRecord(asRecord(query)?.tableSettings)?.columns
    const yAxis = chartSettingsOf(query)?.yAxis
    return columns.map((column, index) => {
        const name = typeof column === 'string' ? column : String(column)
        const pair = typeList[index]
        const type = Array.isArray(pair) && typeof pair[1] === 'string' ? pair[1] : null
        const scalar = sqlScalar(type)
        return {
            name,
            scalar,
            isNumerical: NUMERICAL_SCALARS.has(scalar),
            isDate: DATE_SCALARS.has(scalar),
            format: sqlPresentation(settingsFor(tableColumns, name)) ?? sqlPresentation(settingsFor(yAxis, name)),
        }
    })
}

function cellOf(value: unknown): SqlCell {
    if (value === null || value === undefined) {
        return null
    }
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
        return value
    }
    return JSON.stringify(value) ?? null
}

export function sqlTableView(query: unknown, response: SqlResponseParts): SqlTableView | null {
    if (!isSqlQuery(query) || !Array.isArray(response.result)) {
        return null
    }
    return {
        columns: sqlColumns(response.columns, response.types, query),
        rows: response.result.filter(Array.isArray).map((row: unknown[]) => row.map(cellOf)),
        hasMore: response.hasMore === true,
    }
}

export function autoSqlDisplay(columns: SqlColumnView[], rowCount: number): string {
    const numerical = columns.filter((column) => column.isNumerical)
    if (columns.some((column) => column.isDate) && numerical.length > 0 && rowCount > 1) {
        return 'ActionsLineGraph'
    }
    if (columns.filter((column) => column.scalar === 'STRING').length >= 2 && numerical.length > 0) {
        return 'TwoDimensionalHeatmap'
    }
    if (numerical.length === 1 && columns.length === 1) {
        return 'BoldNumber'
    }
    return numerical.length > 0 ? 'ActionsBar' : 'ActionsTable'
}

/** The saved display, or the Auto display of the result. Null for Auto before a result exists. */
export function effectiveSqlDisplay(query: unknown, table: SqlTableView | null): string | null {
    const saved = savedDisplay(query)
    if (saved) {
        return saved
    }
    return table ? autoSqlDisplay(table.columns, table.rows.length) : null
}

/**
 * The x and y columns. Unset, x is the first date column, else the first column that is not a number, and y is every
 * number column. As the web clears saved axes that no longer fit the result, a saved x column that is missing, or a
 * saved y column that is missing or not a number, drops both back to the defaults. The x column and the breakdown
 * column are never a y series.
 */
export function sqlAxes(query: unknown, columns: SqlColumnView[]): SqlAxes {
    const settings = chartSettingsOf(query)
    const byName = (name: unknown): SqlColumnView | undefined => columns.find((column) => column.name === name)
    const savedXName = asRecord(settings?.xAxis)?.column
    const savedX = typeof savedXName === 'string' ? byName(savedXName) : null
    const savedYNames = Array.isArray(settings?.yAxis)
        ? settings.yAxis.filter(isRecord).map((entry) => entry.column)
        : []
    const savedY = savedYNames.map(byName).filter((column): column is SqlColumnView => column?.isNumerical === true)
    const valid = savedX !== undefined && savedY.length === savedYNames.length
    const x =
        (valid ? savedX : null) ??
        columns.find((column) => column.isDate) ??
        columns.find((column) => !column.isNumerical) ??
        null
    const chosenY = valid && savedY.length > 0 ? savedY : columns.filter((column) => column.isNumerical)
    const breakdown = breakdownColumnOf(query)
    const y = chosenY.filter((column) => column.name !== x?.name && column.name !== breakdown)
    return { x, y }
}

/**
 * The format of a SQL insight's values, for its big number, chart and bar list. A big number uses the first result
 * column's table settings, as HogQLBoldNumber does on the web. Any other display uses the first saved y axis entry's
 * settings, as the web's tooltip and axis do, else the first y column's own format.
 */
export function sqlValuePresentation(query: unknown, columns: unknown, types: unknown): InsightPresentation {
    const raw: InsightPresentation = { kind: 'sql', style: null, prefix: '', suffix: '' }
    const names = Array.isArray(columns) ? columns : []
    if (savedDisplay(query) === 'BoldNumber') {
        const settings = asRecord(asRecord(query)?.tableSettings)?.columns
        const entries = Array.isArray(settings) ? settings.filter(isRecord) : []
        const entry =
            entries.find((candidate) => candidate.column === names[0]) ??
            (names.length === 0 && entries.length === 1 ? entries[0] : undefined)
        return sqlPresentation(entry?.settings) ?? raw
    }
    const yAxis = chartSettingsOf(query)?.yAxis
    const saved = sqlPresentation(Array.isArray(yAxis) ? yAxis.find(isRecord)?.settings : undefined)
    if (saved) {
        return saved
    }
    return sqlAxes(query, sqlColumns(columns, types, query)).y[0]?.format ?? raw
}

/** A specific explanation for a SQL chart the native renderer cannot represent faithfully. */
export function sqlChartReason(query: unknown, table: SqlTableView | null = null): string | undefined {
    const display = effectiveSqlDisplay(query, table)
    if (display === 'BoldNumber') return 'Saved as a big number'
    if (display === 'Metric') return 'SQL metric cards are not supported on mobile yet'
    if (isTransposed(query)) return 'Transposed SQL charts are not supported on mobile yet'
    if (!display || (!LINE_DISPLAYS.has(display) && !BAR_DISPLAYS.has(display))) {
        return 'This SQL visualization cannot be pinned as a chart yet'
    }
    const settings = chartSettingsOf(query)
    if (settings?.stackBars100) return '100% stacked SQL charts are not supported on mobile yet'
    for (const key of ['leftYAxisSettings', 'rightYAxisSettings']) {
        const scale = asRecord(settings?.[key])?.scale
        if (scale && scale !== 'linear') return 'Logarithmic SQL axes are not supported on mobile yet'
    }
    const ys = settings?.yAxis
    if (
        Array.isArray(ys) &&
        ys.some((y) => {
            const series = asRecord(asRecord(asRecord(y)?.settings)?.display)
            return (
                series?.trendLine ||
                (series?.displayType && !['auto', 'line', 'bar', 'area'].includes(String(series.displayType)))
            )
        })
    )
        return 'This SQL series style is not supported on mobile yet'
    if (table) {
        const savedX = asRecord(settings?.xAxis)?.column
        const savedYs = Array.isArray(ys) ? ys.map((y) => asRecord(y)?.column) : []
        if (
            [savedX, ...savedYs].some(
                (name) => typeof name === 'string' && !table.columns.some((column) => column.name === name)
            )
        ) {
            return 'Saved chart columns are unavailable'
        }
        const { x, y } = sqlAxes(query, table.columns)
        if (!x || !y.length) return 'Choose chart axes on the web first'
        if (!x.isDate && breakdownColumnOf(query))
            return 'SQL category breakdown charts are not supported on mobile yet'
    }
    return undefined
}

function seriesPresentation(
    query: unknown,
    column: SqlColumnView,
    kind: MetricChartKind
): Pick<InsightSeriesView, 'color' | 'chartKind' | 'axis' | 'area' | 'startAtZero' | 'format'> {
    const settings = chartSettingsOf(query)
    const saved = settingsFor(settings?.yAxis, column.name)
    const display = asRecord(asRecord(saved)?.display)
    const axis = display?.yAxisPosition === 'right' ? 'right' : 'left'
    const axisSettings = asRecord(settings?.[axis === 'right' ? 'rightYAxisSettings' : 'leftYAxisSettings'])
    return {
        color: typeof display?.color === 'string' ? display.color : undefined,
        chartKind:
            display?.displayType === 'bar'
                ? 'bar'
                : display?.displayType === 'line' || display?.displayType === 'area'
                  ? 'line'
                  : kind,
        axis,
        area: display?.displayType === 'area' || savedDisplay(query) === 'ActionsAreaGraph',
        startAtZero:
            typeof axisSettings?.startAtZero === 'boolean' ? axisSettings.startAtZero : settings?.yAxisAtZero === true,
        format: sqlPresentation(saved) ?? column.format ?? { kind: 'sql', style: null, prefix: '', suffix: '' },
    }
}

/**
 * The phone's display from the saved query alone, so a tile keeps one display while it loads. Auto is a table until
 * the result arrives, since the phone can draw any result as a table.
 */
export function sqlQueryDisplay(query: unknown): SqlPhoneDisplay {
    if (isTransposed(query)) {
        return 'web'
    }
    const display = savedDisplay(query)
    if (display === null || display === 'ActionsTable') {
        return 'table'
    }
    if (NUMBER_DISPLAYS.has(display)) {
        return 'number'
    }
    if (LINE_DISPLAYS.has(display) || BAR_DISPLAYS.has(display)) {
        return sqlChartReason(query) ? 'web' : 'chart'
    }
    return RANKING_DISPLAYS.has(display) ? 'bars' : 'web'
}

/**
 * Saved line and bar charts accept dates or categories. Auto retains its table, date-chart and ranking rules.
 * A chart the phone cannot build faithfully opens on the web.
 */
export function sqlResultDisplay(query: unknown, table: SqlTableView): SqlPhoneDisplay {
    if (isTransposed(query)) {
        return 'web'
    }
    const display = effectiveSqlDisplay(query, table)
    if (display === null || display === 'ActionsTable') {
        return 'table'
    }
    if (NUMBER_DISPLAYS.has(display)) {
        return 'number'
    }
    const { x, y } = sqlAxes(query, table.columns)
    if (!x || y.length === 0) {
        return 'web'
    }
    if ((LINE_DISPLAYS.has(display) || BAR_DISPLAYS.has(display)) && (x.isDate || savedDisplay(query) !== null)) {
        return sqlChartReason(query, table) ? 'web' : 'chart'
    }
    // A breakdown column or a second y column gives several values per x value, which one bar per row cannot show.
    if ((display === 'ActionsBar' || RANKING_DISPLAYS.has(display)) && breakdownColumnOf(query) === null) {
        return y.length === 1 ? 'bars' : 'web'
    }
    return 'web'
}

function displayFor(query: unknown, table: SqlTableView | null): SqlPhoneDisplay {
    return table ? sqlResultDisplay(query, table) : sqlQueryDisplay(query)
}

export function sqlChartKind(query: unknown, table: SqlTableView | null): MetricChartKind | null {
    if (displayFor(query, table) !== 'chart') {
        return null
    }
    const display = effectiveSqlDisplay(query, table)
    const yAxis = chartSettingsOf(query)?.yAxis
    const first = Array.isArray(yAxis) ? asRecord(yAxis[0]) : undefined
    const displayType = asRecord(asRecord(first?.settings)?.display)?.displayType
    return (display !== null && BAR_DISPLAYS.has(display)) || displayType === 'bar' ? 'bar' : 'line'
}

/** The bucket size from the median gap between distinct dates. A few hours of slack keeps DST days daily. */
export function sqlInterval(points: readonly Pick<MetricPoint, 'at'>[]): MetricInterval {
    const times = [...new Set(points.map((point) => parseBucketStart(point.at)).filter(Number.isFinite))].sort(
        (a, b) => a - b
    )
    const gaps = times.slice(1).map((time, index) => time - (times[index] ?? time))
    if (gaps.length === 0) {
        return 'day'
    }
    gaps.sort((a, b) => a - b)
    const median = gaps[Math.floor(gaps.length / 2)] ?? DAY_MS
    if (median < DAY_MS - 3 * HOUR_MS) {
        return 'hour'
    }
    if (median < 6 * DAY_MS) {
        return 'day'
    }
    return median < 28 * DAY_MS ? 'week' : 'month'
}

// A date, or a datetime as the API writes it: `T` or a space, optional seconds and fraction, and an offset.
const DATE_CELL = /^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2})(:\d{2})?(?:\.\d+)?)?(?:Z|[+-]\d{2}(?::?\d{2})?)?$/

/**
 * The x value as a bucket start, or null when the cell is no date. A datetime keeps the wall clock the server wrote,
 * without its offset or fraction, so `parseBucketStart` reads it in local time like a trends bucket and like the
 * table shows it.
 */
function dateKey(cell: SqlCell | undefined): string | null {
    const match = typeof cell === 'string' ? DATE_CELL.exec(cell.trim()) : null
    if (!match?.[1]) {
        return null
    }
    const at = match[2] ? `${match[1]} ${match[2]}${match[3] ?? ':00'}` : match[1]
    return Number.isFinite(parseBucketStart(at)) ? at : null
}

function cellLabel(cell: SqlCell): string {
    return cell === null ? 'None' : String(cell)
}

function groupValue(cell: SqlCell | undefined): string | number | null {
    if (cell === undefined) {
        return null
    }
    return typeof cell === 'boolean' ? String(cell) : cell
}

function runningSum<T extends MetricPoint>(points: T[]): T[] {
    let total = 0
    return points.map((point) => {
        if (!Number.isFinite(point.value)) {
            return point
        }
        total += point.value
        return { ...point, value: total }
    })
}

function columnIndex(table: SqlTableView, column: SqlColumnView | null | undefined): number {
    return column ? table.columns.findIndex((candidate) => candidate.name === column.name) : -1
}

/** Valid chart columns can be pinned even when the current result is empty. */
export function hasSqlChartSeries(query: unknown, table: SqlTableView): boolean {
    if (sqlResultDisplay(query, table) !== 'chart') {
        return false
    }
    const { x, y } = sqlAxes(query, table.columns)
    const xIndex = columnIndex(table, x)
    return (
        y.length > 0 &&
        (!x?.isDate || table.rows.length === 0 || table.rows.some((row) => dateKey(row[xIndex]) !== null))
    )
}

/**
 * Category charts preserve row order and labels. Date charts have one series per y column and breakdown. Every series has a
 * point at every date of the result, in date order, because the chart pairs series by index. A date with no finite
 * value is NaN, and rows that share a date and a series add up. Empty when the display is not a supported chart.
 */
export function sqlSeriesViews(query: unknown, table: SqlTableView): InsightSeriesView[] {
    if (sqlResultDisplay(query, table) !== 'chart') {
        return []
    }
    const { x, y } = sqlAxes(query, table.columns)
    const xIndex = columnIndex(table, x)
    const display = effectiveSqlDisplay(query, table)
    const kind = BAR_DISPLAYS.has(display ?? '') ? 'bar' : 'line'
    const cumulative = display === 'ActionsLineGraphCumulative'
    if (!x?.isDate) {
        return y.map((column, seriesIndex) => {
            const columnIndex = table.columns.indexOf(column)
            const display = asRecord(asRecord(settingsFor(chartSettingsOf(query)?.yAxis, column.name))?.display)
            const points = table.rows.map((row, index) => ({
                at: String(index),
                label: cellLabel(row[xIndex] ?? null),
                value:
                    sqlCellNumber(row[columnIndex]) ??
                    (chartSettingsOf(query)?.showNullsAsZero && row[columnIndex] === null ? 0 : Number.NaN),
            }))
            return {
                key: `sql:${column.name}:null`,
                label: typeof display?.label === 'string' && display.label ? display.label : column.name,
                ...seriesPresentation(query, column, kind),
                points: cumulative ? runningSum(points) : points,
                compare: null,
                seriesIndex,
                breakdownValue: null,
            }
        })
    }
    const breakdown = breakdownColumnOf(query)
    const breakdownIndex = breakdown ? table.columns.findIndex((column) => column.name === breakdown) : -1
    const yIndexes = y.map((column) => columnIndex(table, column))
    const dates = new Map<string, number>()
    // One map per y column: group, then date, then the sum. A Map keeps the groups in the order they first appear.
    const sums = y.map(() => new Map<string | number | null, Map<string, number>>())
    const groups = new Set<string | number | null>()
    for (const row of table.rows) {
        const at = dateKey(row[xIndex])
        if (at !== null && !dates.has(at)) {
            dates.set(at, parseBucketStart(at))
        }
        const group = breakdownIndex >= 0 ? groupValue(row[breakdownIndex]) : null
        groups.add(group)
        if (at === null) {
            continue
        }
        yIndexes.forEach((yIndex, seriesIndex) => {
            const value = sqlCellNumber(row[yIndex])
            if (value === undefined) {
                return
            }
            const byGroup = sums[seriesIndex]
            const byDate = byGroup?.get(group) ?? new Map<string, number>()
            byDate.set(at, (byDate.get(at) ?? 0) + value)
            byGroup?.set(group, byDate)
        })
    }
    const axis = [...dates.entries()].sort((a, b) => a[1] - b[1]).map(([at]) => at)
    return y.flatMap((column, seriesIndex) =>
        [...groups].map((group): InsightSeriesView => {
            const byDate = sums[seriesIndex]?.get(group)
            const points = axis.map((at) => ({
                at,
                value: byDate?.get(at) ?? (chartSettingsOf(query)?.showNullsAsZero ? 0 : Number.NaN),
            }))
            const display = asRecord(asRecord(settingsFor(chartSettingsOf(query)?.yAxis, column.name))?.display)
            const name = typeof display?.label === 'string' && display.label ? display.label : column.name
            const label = breakdownIndex < 0 ? name : y.length > 1 ? `${name} - ${cellLabel(group)}` : cellLabel(group)
            return {
                // JSON keeps NULL and the empty string apart.
                key: `sql:${column.name}:${JSON.stringify(group)}`,
                label,
                ...seriesPresentation(query, column, kind),
                points: cumulative ? runningSum(points) : points,
                compare: null,
                seriesIndex,
                breakdownValue: group,
            }
        })
    )
}

/**
 * One bar per row: the x cell is the label and the first y column the value. Rows keep the server's order, because a
 * SQL author orders them on purpose. Null when the display is not bars.
 */
export function sqlRankingView(query: unknown, table: SqlTableView): RankingView | null {
    if (sqlResultDisplay(query, table) !== 'bars') {
        return null
    }
    const { x, y } = sqlAxes(query, table.columns)
    const xIndex = columnIndex(table, x)
    const yIndex = columnIndex(table, y[0])
    const rows = table.rows.flatMap((row, index): RankedValueView[] => {
        const value = sqlCellNumber(row[yIndex])
        if (value === undefined) {
            return []
        }
        const label = cellLabel(row[xIndex] ?? null)
        return [{ key: `${index}:${label}`, label, value }]
    })
    return { rows, total: rows.reduce((total, row) => total + row.value, 0) }
}
