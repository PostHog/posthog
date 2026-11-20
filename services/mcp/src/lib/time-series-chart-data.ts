import { isRecord } from '@/lib/plain-object'
import { POSTHOG_INFORMATIONAL_RESPONSE_KEY } from '@/tools/types'

type Point = [string, number]

interface NamedSeries {
    name: string
    data: Point[]
}

type JsonRecord = Record<string, unknown>

const TIME_PATTERN = /^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}(?::?\d{2})?)?)?$/

// Chart readers refuse data of 64 KiB or more, and every point is also text the model reads.
const MAX_BLOCK_BYTES = 48 * 1024
const MAX_SERIES = 25
const MIN_POINTS = 2
// The smallest point, `["2026-11-03",1],`, is 17 bytes, so more points than this cannot fit in one block.
const MAX_POINTS = Math.floor(MAX_BLOCK_BYTES / 17)
// A text table long enough to exceed this holds more than one block can carry, so it is not read.
const MAX_TABLE_CHARS = 128 * 1024
const MAX_LABEL_CHARS = 60

const TIME_ARRAY_KEYS = ['days', 'dates']
const VALUE_ARRAY_KEYS = ['data', 'values', 'exposure_counts']
const SERIES_NAME_KEYS = ['custom_name', 'label', 'name', 'variant', 'metric_name']
const ROW_TIME_KEYS = ['time', 'timestamp', 'day', 'date', 'bucket_start', 'date_from']
// The end of a bucket repeats what the axis says. Any other date column is a dimension, such as a cohort.
const BUCKET_END_KEYS = new Set(['date_to', 'bucket_end', 'end_time'])
const ID_COLUMN = /(?:^|_)id$/i

const CONTAINER_KEYS = ['results', 'series', 'days', 'daily', 'sparkline', 'ranges', 'timeseries']

const BREAKDOWN_DISPLAY_NAMES: Record<string, string> = {
    $$_posthog_breakdown_other_$$: 'Other',
    $$_posthog_breakdown_null_$$: 'None',
}

/** Counts what an adapter reads, so an oversized result stops before its points are copied. */
class Budget {
    private series = 0
    private points = 0

    admit(pointCount: number): boolean {
        this.series += 1
        this.points += pointCount
        return this.series <= MAX_SERIES && this.points <= MAX_POINTS
    }
}

// An adapter returns this when the result holds more than one block can carry.
type AdapterResult = NamedSeries[] | null

function isTime(value: unknown): value is string {
    return typeof value === 'string' && TIME_PATTERN.test(value)
}

function isFiniteNumber(value: unknown): value is number {
    return typeof value === 'number' && Number.isFinite(value)
}

function firstString(record: JsonRecord, keys: string[]): string | undefined {
    for (const key of keys) {
        const value = record[key]
        if (typeof value === 'string' && value.trim() !== '') {
            return value
        }
    }
    return undefined
}

function firstArray(record: JsonRecord, keys: string[]): unknown[] | undefined {
    for (const key of keys) {
        const value = record[key]
        if (Array.isArray(value)) {
            return value
        }
    }
    return undefined
}

function displayBreakdownValue(value: unknown): string {
    const parts = (Array.isArray(value) ? value : [value]).map((part) => {
        const text = String(part)
        return BREAKDOWN_DISPLAY_NAMES[text] ?? text
    })
    return parts.join(', ')
}

function zipPoints(times: unknown[], values: unknown[]): Point[] | undefined {
    if (times.length !== values.length || !times.every(isTime)) {
        return undefined
    }
    const points: Point[] = []
    times.forEach((time, index) => {
        const value = values[index]
        if (isFiniteNumber(value)) {
            points.push([time as string, value])
        }
    })
    return points
}

function fromParallelArrays(items: unknown[], budget: Budget): AdapterResult {
    const series: NamedSeries[] = []
    for (const [index, item] of items.entries()) {
        // The previous period of a comparison covers other dates. On one time axis it would
        // draw as a second line beside the current one, not on top of it.
        if (!isRecord(item) || item.compare_label === 'previous') {
            continue
        }
        const times = firstArray(item, TIME_ARRAY_KEYS)
        const values = firstArray(item, VALUE_ARRAY_KEYS)
        if (!times || !values) {
            continue
        }
        if (!budget.admit(times.length)) {
            return null
        }
        const data = zipPoints(times, values)
        if (!data) {
            continue
        }
        const baseName = firstString(item, SERIES_NAME_KEYS)
        const breakdown =
            item.breakdown_value === undefined || item.breakdown_value === null
                ? undefined
                : displayBreakdownValue(item.breakdown_value)
        // A breakdown series is labelled with its raw breakdown value, so the label only adds
        // information when it names something else, such as the event of a multi-series query.
        const name =
            baseName !== undefined && breakdown !== undefined && displayBreakdownValue(baseName) !== breakdown
                ? `${baseName} (${breakdown})`
                : (breakdown ?? baseName ?? `Series ${index + 1}`)
        series.push({ name, data })
    }
    return series
}

function fromSharedAxis(record: JsonRecord, budget: Budget): AdapterResult {
    const times = record.labels
    const items = record.series
    if (!Array.isArray(times) || !Array.isArray(items)) {
        return []
    }
    const series: NamedSeries[] = []
    for (const [index, item] of items.entries()) {
        if (!isRecord(item) || !Array.isArray(item.values)) {
            continue
        }
        if (!budget.admit(times.length)) {
            return null
        }
        const data = zipPoints(times, item.values)
        if (data) {
            series.push({ name: firstString(item, ['name']) ?? `Series ${index + 1}`, data })
        }
    }
    return series
}

function describeLabels(labels: unknown): string | undefined {
    if (!isRecord(labels)) {
        return undefined
    }
    const pairs = Object.entries(labels)
        .filter(([, value]) => typeof value === 'string' || typeof value === 'number')
        .map(([key, value]) => `${key}=${value}`)
    return pairs.length > 0 ? pairs.join(', ') : undefined
}

function fromPointLists(items: unknown[], budget: Budget): AdapterResult {
    const series: NamedSeries[] = []
    for (const [index, item] of items.entries()) {
        if (!isRecord(item) || !Array.isArray(item.points)) {
            continue
        }
        if (!budget.admit(item.points.length)) {
            return null
        }
        const times: unknown[] = []
        const values: unknown[] = []
        for (const point of item.points) {
            times.push(isRecord(point) ? (point.time ?? point.timestamp) : undefined)
            values.push(isRecord(point) ? point.value : undefined)
        }
        const data = zipPoints(times, values)
        if (!data) {
            continue
        }
        const metric = typeof item.metric_name === 'string' ? item.metric_name : undefined
        const labels = describeLabels(item.labels)
        const name = [metric, labels].filter(Boolean).join(' ') || `Series ${index + 1}`
        series.push({ name, data })
    }
    return series
}

type ColumnKind = 'time' | 'number' | 'text' | 'empty' | 'mixed'

function kindOf(value: unknown): ColumnKind {
    if (value === undefined || value === null) {
        return 'empty'
    }
    if (isFiniteNumber(value)) {
        return 'number'
    }
    if (typeof value !== 'string') {
        return 'mixed'
    }
    return isTime(value) ? 'time' : 'text'
}

function columnKind(records: JsonRecord[], key: string): ColumnKind {
    let kind: ColumnKind = 'empty'
    for (const row of records) {
        const cell = kindOf(row[key])
        if (cell === 'empty' || cell === kind) {
            continue
        }
        if (kind === 'empty') {
            kind = cell
        } else if ((kind === 'time' || kind === 'text') && (cell === 'time' || cell === 'text')) {
            kind = 'text'
        } else {
            return 'mixed'
        }
    }
    return kind
}

function groupLabel(key: string, cell: unknown): string {
    if (cell === undefined || cell === null) {
        return NULL_CELL
    }
    if (cell === '') {
        return '(empty)'
    }
    const label = ID_COLUMN.test(key) ? `${key}=${cell}` : String(cell)
    return label.length > MAX_LABEL_CHARS ? `${label.slice(0, MAX_LABEL_CHARS - 1)}…` : label
}

function fromRows(rows: unknown[], budget: Budget): AdapterResult {
    if (rows.length > MAX_POINTS) {
        return null
    }
    if (!rows.every(isRecord)) {
        return []
    }
    const records = rows as JsonRecord[]
    const keys = new Set<string>()
    for (const row of records) {
        for (const key of Object.keys(row)) {
            keys.add(key)
        }
    }
    const kinds = new Map<string, ColumnKind>()
    for (const key of keys) {
        const kind = columnKind(records, key)
        if (kind === 'mixed') {
            return []
        }
        kinds.set(key, kind)
    }
    const isAxis = (key: string): boolean => kinds.get(key) === 'time' && records.every((row) => isTime(row[key]))
    // SQL columns carry whatever alias the query gave them, so any column of times will do.
    const timeKey = ROW_TIME_KEYS.find(isAxis) ?? [...keys].find(isAxis)
    if (!timeKey) {
        return []
    }
    const valueKeys: string[] = []
    const splitKeys: string[] = []
    for (const [key, kind] of kinds) {
        if (key === timeKey || kind === 'empty' || BUCKET_END_KEYS.has(key)) {
            continue
        }
        // A numeric ID such as `team_id` names a group. Drawn as a value, it would be a meaningless line.
        if (kind === 'number' && !ID_COLUMN.test(key)) {
            valueKeys.push(key)
        } else {
            splitKeys.push(key)
        }
    }
    if (valueKeys.length === 0) {
        return []
    }
    if (records.length * valueKeys.length > MAX_POINTS) {
        return null
    }

    // Groups are keyed by their exact cells, so NULL, an empty string, and values that contain
    // the display separator stay apart even when their labels read alike.
    const byGroup = new Map<string, NamedSeries>()
    for (const row of records) {
        const cells = splitKeys.map((key) => row[key] ?? null)
        for (const valueKey of valueKeys) {
            const value = row[valueKey]
            if (!isFiniteNumber(value)) {
                continue
            }
            const groupKey = JSON.stringify([cells, valueKey])
            let series = byGroup.get(groupKey)
            if (!series) {
                if (!budget.admit(0)) {
                    return null
                }
                const group = splitKeys.map((key, index) => groupLabel(key, cells[index])).join(', ')
                const name = group === '' ? valueKey : valueKeys.length > 1 ? `${group} ${valueKey}` : group
                series = { name, data: [] }
                byGroup.set(groupKey, series)
            }
            series.data.push([row[timeKey] as string, value])
        }
    }
    return withUniqueNames([...byGroup.values()])
}

function withUniqueNames(series: NamedSeries[]): NamedSeries[] {
    const seen = new Map<string, number>()
    for (const entry of series) {
        const count = (seen.get(entry.name) ?? 0) + 1
        seen.set(entry.name, count)
        if (count > 1) {
            entry.name = `${entry.name} (${count})`
        }
    }
    return series
}

const NUMBER_CELL = /^-?\d+(?:\.\d+)?(?:e[+-]?\d+)?$/i
// The SQL results formatter (`ee/hogai/context/insight/format/sql.py`) writes SQL NULL as this marker.
const NULL_CELL = '(null)'

function parseCell(cell: string): string | number | null {
    if (cell === NULL_CELL) {
        return null
    }
    return NUMBER_CELL.test(cell) ? Number(cell) : cell
}

const BRACKETED_NOTICE = /^\[.*\]$/

/**
 * Accepts only the footers that `ee/hogai/context/insight/query_executor.py` writes after the table:
 * a bracketed preview notice, and the warehouse suggestions, which are a bracketed header followed
 * by `- ` lines. The formatter does not escape a newline in a cell, so a newline in the last cell of
 * the last row continues on the next line. That line must not be read as a footer, because the row
 * would then lose part of its label and join the series of another group.
 */
function isFooter(lines: string[]): boolean {
    let inList = false
    for (const line of lines) {
        if (line === '') {
            inList = false
        } else if (BRACKETED_NOTICE.test(line)) {
            inList = true
        } else if (!(inList && line.startsWith('- '))) {
            return false
        }
    }
    return true
}

/**
 * Reads the pipe-delimited table that `execute-sql` returns as text into rows. Notices without a
 * `|` come before the table (taxonomy warnings). The formatter does not escape a `|` inside a cell,
 * so a table whose lines disagree on their cell count cannot be read safely and is skipped.
 */
function rowsFromPipeTable(text: string): JsonRecord[] | null {
    if (text.length > MAX_TABLE_CHARS) {
        return null
    }
    if (!/\d{4}-\d{2}-\d{2}/.test(text)) {
        return []
    }
    const textLines = text.split('\n')
    const lines = textLines.map((line) => line.split('|'))
    const start = lines.findIndex((cells) => cells.length >= 2)
    if (start === -1) {
        return []
    }
    const width = lines[start]!.length
    let end = start + 1
    while (end < lines.length && lines[end]!.length === width) {
        end++
    }
    if (!isFooter(textLines.slice(end))) {
        return []
    }
    if (end - start - 1 > MAX_POINTS) {
        return null
    }
    const [header, ...body] = lines.slice(start, end)
    if (!header || new Set(header).size !== header.length) {
        return []
    }
    return body.map((cells) => {
        const row: JsonRecord = {}
        header.forEach((column, index) => {
            row[column] = parseCell(cells[index]!)
        })
        return row
    })
}

function seriesFrom(candidate: unknown): AdapterResult {
    if (typeof candidate === 'string') {
        const rows = rowsFromPipeTable(candidate)
        return rows === null ? null : fromRows(rows, new Budget())
    }
    if (isRecord(candidate)) {
        return fromSharedAxis(candidate, new Budget())
    }
    if (!Array.isArray(candidate)) {
        return []
    }
    for (const adapter of [fromParallelArrays, fromPointLists, fromRows]) {
        const series = adapter(candidate, new Budget())
        if (series === null || series.length > 0) {
            return series
        }
    }
    return []
}

function candidatesIn(result: unknown): unknown[] {
    if (!isRecord(result)) {
        return [result]
    }
    const nested = isRecord(result.exposures) ? [result.exposures.timeseries] : []
    return [result, ...CONTAINER_KEYS.map((key) => result[key]), ...nested]
}

function repeatsATime(entry: NamedSeries): boolean {
    return new Set(entry.data.map(([time]) => time)).size !== entry.data.length
}

function findTimeSeries(result: unknown): NamedSeries[] {
    for (const candidate of candidatesIn(result)) {
        const series = seriesFrom(candidate)
        if (series === null) {
            return []
        }
        const drawable = series.filter((entry) => entry.data.length >= MIN_POINTS)
        if (drawable.length > 0) {
            // A series with two values at one time means a column was read wrongly. For example, a
            // numeric dimension such as `hour` or `status` was read as a value, so the rows it
            // should split were merged into one line.
            return drawable.some(repeatsATime) ? [] : drawable
        }
    }
    return []
}

const TIME_WITH_UTC_OFFSET = /^(.+[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)[+-]\d{2}(?::?\d{2})?$/
const utf8 = new TextEncoder()
const MIDNIGHT = /^(\d{4}-\d{2}-\d{2})[T ]00:00(?::00(?:\.0+)?)?Z?$/

/**
 * Chart readers draw a time that carries a UTC offset in UTC, and a tool result has no way to name
 * another display zone. A bucket that the project timezone opened at `2026-11-10T00:00:00-08:00` is
 * then labelled `Nov 10 08:00`, or the previous day for a zone east of UTC. A time with no zone is
 * drawn as written, so dropping the offset keeps the project's wall-clock time, and a result of
 * midnights becomes dates. Times in `Z` keep their zone, because those tools bucket in UTC.
 */
function toWallClockTimes(series: NamedSeries[]): void {
    let allMidnight = true
    for (const entry of series) {
        for (const point of entry.data) {
            point[0] = point[0].replace(TIME_WITH_UTC_OFFSET, '$1')
            allMidnight &&= MIDNIGHT.test(point[0])
        }
    }
    if (allMidnight) {
        for (const entry of series) {
            for (const point of entry.data) {
                point[0] = point[0].slice(0, 10)
            }
        }
    }
}

// The model reads the block too. Without this line it reads the same values twice and may quote the JSON.
export const CHART_DATA_PREAMBLE =
    'Chart data: the JSON below repeats the values above as named series, so the client can draw them. Read and quote the output above.'

export function buildTimeSeriesChartData(result: unknown): string | undefined {
    // An informational response fences workspace-controlled text, such as project names. Labels
    // copied into this block would sit outside that fence.
    if (typeof result === 'object' && result !== null && POSTHOG_INFORMATIONAL_RESPONSE_KEY in result) {
        return undefined
    }
    const series = findTimeSeries(result)
    if (series.length === 0) {
        return undefined
    }
    toWallClockTimes(series)
    // SQL results often come newest first. Every time in one result has the same format, so text
    // order is time order.
    for (const entry of series) {
        entry.data.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    }
    const block = JSON.stringify({ series })
    // UTF-8 never takes fewer bytes than UTF-16 code units, so a long string fails without encoding.
    if (block.length > MAX_BLOCK_BYTES || utf8.encode(block).length > MAX_BLOCK_BYTES) {
        return undefined
    }
    return `${CHART_DATA_PREAMBLE}\n${block}`
}
