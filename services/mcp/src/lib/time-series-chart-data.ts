/**
 * Finds the values-over-time series in a tool result and writes them as one JSON block in the
 * named-series shape, `{"series":[{"name":"…","data":[["2026-11-03",123],…]}]}`. Terminal agents
 * that draw charts from tool output read this shape. Our formatted tables and TOON payloads keep
 * the dates and the values in separate columns or arrays, so those agents cannot chart them.
 */

import { isRecord } from '@/lib/plain-object'

type Point = [string, number]

interface NamedSeries {
    name: string
    data: Point[]
}

type JsonRecord = Record<string, unknown>

// Accepts a date alone, or a date with a time and an optional zone. A chart reader rejects the
// whole block when one time does not parse, so a series with any other time format is skipped.
const TIME_PATTERN = /^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}(?::?\d{2})?)?)?$/

// Chart readers refuse data of 64 KiB or more, and every point is also text the model reads.
const MAX_BLOCK_BYTES = 48 * 1024
const MAX_SERIES = 25
const MIN_POINTS = 2
// The smallest point, `["2026-11-03",1],`, is 17 bytes, so a table with more rows than this cannot
// fit in one block. Such a table is not read at all.
const MAX_ROWS = Math.floor(MAX_BLOCK_BYTES / 17)

const TIME_ARRAY_KEYS = ['days', 'dates']
const VALUE_ARRAY_KEYS = ['data', 'values', 'exposure_counts']
const SERIES_NAME_KEYS = ['custom_name', 'label', 'name', 'variant', 'metric_name']
const ROW_TIME_KEYS = ['time', 'timestamp', 'day', 'date', 'bucket_start', 'date_from']
const ID_COLUMN = /(?:^|_)id$/i

const CONTAINER_KEYS = ['results', 'series', 'days', 'daily', 'sparkline', 'ranges', 'timeseries']

const BREAKDOWN_DISPLAY_NAMES: Record<string, string> = {
    $$_posthog_breakdown_other_$$: 'Other',
    $$_posthog_breakdown_null_$$: 'None',
}

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

/** Pairs the times and values. Returns undefined when any time is not a date, so a partly dated series is not drawn with gaps. */
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

function fromParallelArrays(items: unknown[]): NamedSeries[] {
    const series: NamedSeries[] = []
    items.forEach((item, index) => {
        if (!isRecord(item)) {
            return
        }
        // The previous period of a comparison covers other dates. On one time axis it would
        // draw as a second line beside the current one, not on top of it.
        if (item.compare_label === 'previous') {
            return
        }
        const times = firstArray(item, TIME_ARRAY_KEYS)
        const values = firstArray(item, VALUE_ARRAY_KEYS)
        const data = times && values ? zipPoints(times, values) : undefined
        if (!data) {
            return
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
    })
    return series
}

function fromSharedAxis(record: JsonRecord): NamedSeries[] {
    const times = record.labels
    const items = record.series
    if (!Array.isArray(times) || !Array.isArray(items)) {
        return []
    }
    const series: NamedSeries[] = []
    items.forEach((item, index) => {
        if (!isRecord(item) || !Array.isArray(item.values)) {
            return
        }
        const data = zipPoints(times, item.values)
        if (data) {
            series.push({ name: firstString(item, ['name']) ?? `Series ${index + 1}`, data })
        }
    })
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

function fromPointLists(items: unknown[]): NamedSeries[] {
    const series: NamedSeries[] = []
    items.forEach((item, index) => {
        if (!isRecord(item) || !Array.isArray(item.points)) {
            return
        }
        const times: unknown[] = []
        const values: unknown[] = []
        for (const point of item.points) {
            if (!isRecord(point)) {
                return
            }
            times.push(point.time ?? point.timestamp)
            values.push(point.value)
        }
        const data = zipPoints(times, values)
        if (!data) {
            return
        }
        const metric = typeof item.metric_name === 'string' ? item.metric_name : undefined
        const labels = describeLabels(item.labels)
        const name = [metric, labels].filter(Boolean).join(' ') || `Series ${index + 1}`
        series.push({ name, data })
    })
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

/** One pass over the rows for one column. A column of times with a gap reads as text, so it cannot be the time axis. */
function columnKind(records: JsonRecord[], key: string): ColumnKind {
    let kind: ColumnKind = 'empty'
    let hasGap = false
    for (const row of records) {
        const cell = kindOf(row[key])
        if (cell === 'empty') {
            hasGap = true
        } else if (kind === 'empty' || kind === cell) {
            kind = cell
        } else if ((kind === 'time' || kind === 'text') && (cell === 'time' || cell === 'text')) {
            kind = 'text'
        } else {
            return 'mixed'
        }
    }
    return kind === 'time' && hasGap ? 'text' : kind
}

function fromRows(rows: unknown[]): NamedSeries[] {
    if (rows.length > MAX_ROWS || !rows.every(isRecord)) {
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
    // SQL columns carry whatever alias the query gave them, so any column of times will do.
    const timeKey =
        ROW_TIME_KEYS.find((key) => kinds.get(key) === 'time') ?? [...keys].find((key) => kinds.get(key) === 'time')
    if (!timeKey) {
        return []
    }
    // A numeric ID such as `team_id` names a group. Drawn as a value, it would be a meaningless line.
    const valueKeys: string[] = []
    const splitKeys: string[] = []
    for (const [key, kind] of kinds) {
        if (key === timeKey || kind === 'empty') {
            continue
        }
        if (kind === 'number' && !ID_COLUMN.test(key)) {
            valueKeys.push(key)
        } else {
            splitKeys.push(key)
        }
    }
    if (valueKeys.length === 0) {
        return []
    }
    const namesValues = valueKeys.length > 1
    const splitByIds = splitKeys.map((key) => ID_COLUMN.test(key))

    const byName = new Map<string, Point[]>()
    for (const row of records) {
        let group = ''
        splitKeys.forEach((key, index) => {
            const cell = row[key]
            if (cell === undefined || cell === null || cell === '') {
                return
            }
            const part = splitByIds[index] ? `${key}=${cell}` : String(cell)
            group = group === '' ? part : `${group}, ${part}`
        })
        for (const valueKey of valueKeys) {
            const value = row[valueKey]
            if (!isFiniteNumber(value)) {
                continue
            }
            const name = group === '' ? valueKey : namesValues ? `${group} ${valueKey}` : group
            let points = byName.get(name)
            if (!points) {
                points = []
                byName.set(name, points)
            }
            points.push([row[timeKey] as string, value])
        }
    }
    return [...byName].map(([name, data]) => ({ name, data }))
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

/**
 * Reads the pipe-delimited table that `execute-sql` returns as text into rows. Notices may come
 * before the table (taxonomy warnings) or after it (a truncated-preview line), so the table is the
 * run of lines at the end that all have the same number of cells, and its first line is the header.
 */
function rowsFromPipeTable(text: string): JsonRecord[] {
    if (!/\d{4}-\d{2}-\d{2}/.test(text)) {
        return []
    }
    const lines = text.split('\n').filter((line) => line.trim() !== '')
    while (lines.length > 0 && lines[lines.length - 1]!.startsWith('[')) {
        lines.pop()
    }
    const table: string[][] = []
    for (let index = lines.length - 1; index >= 0; index--) {
        const cells = lines[index]!.split('|')
        if (table.length > 0 && cells.length !== table[0]!.length) {
            break
        }
        if (table.length > MAX_ROWS) {
            return []
        }
        table.unshift(cells)
    }
    const [header, ...body] = table
    if (!header || header.length < 2 || new Set(header).size !== header.length) {
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

function seriesFrom(candidate: unknown): NamedSeries[] {
    if (typeof candidate === 'string') {
        return fromRows(rowsFromPipeTable(candidate))
    }
    if (isRecord(candidate)) {
        return fromSharedAxis(candidate)
    }
    if (!Array.isArray(candidate)) {
        return []
    }
    for (const adapter of [fromParallelArrays, fromPointLists, fromRows]) {
        const series = adapter(candidate)
        if (series.length > 0) {
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

function findTimeSeries(result: unknown): NamedSeries[] {
    for (const candidate of candidatesIn(result)) {
        const series = seriesFrom(candidate).filter((entry) => entry.data.length >= MIN_POINTS)
        if (series.length > 0) {
            return series
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

export function buildTimeSeriesChartData(result: unknown): string | undefined {
    const series = findTimeSeries(result)
    if (series.length === 0 || series.length > MAX_SERIES) {
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
    return block
}
