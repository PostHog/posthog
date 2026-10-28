import type { StoryEvidenceChartData } from './explainChartTypes'

type Series = StoryEvidenceChartData['series']

interface Points {
    points: string[]
    series: Series
}

const MAX_POINTS = 200
const MAX_BREAKDOWN_SERIES = 10
const TIMESTAMP = /^\d{4}-(?<month>\d{2})-(?<day>\d{2})(?:[T ](?<time>\d{2}:\d{2}))?/
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function numberOrNull(value: unknown): number | null {
    return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function isNumberColumn(rows: unknown[][], index: number): boolean {
    return (
        rows.some((row) => numberOrNull(row[index]) !== null) &&
        rows.every((row) => row[index] === null || numberOrNull(row[index]) !== null)
    )
}

function isLongShape(rows: unknown[][]): boolean {
    return rows[0]!.length >= 3 && !isNumberColumn(rows, 1) && isNumberColumn(rows, 2)
}

/** `hour, safari, chrome`: one series per number column. */
function wideSeries(columns: string[], rows: unknown[][]): Points {
    const kept = rows.slice(0, MAX_POINTS)
    const valueColumns = columns.map((_, index) => index).filter((index) => index > 0 && isNumberColumn(rows, index))
    return {
        points: kept.map((row) => String(row[0])),
        series: valueColumns.map((index) => ({
            name: columns[index]!,
            values: kept.map((row) => numberOrNull(row[index])),
        })),
    }
}

/** `hour, browser, failures`: one series per browser, with a gap where a browser has no row for an hour. */
function longSeries(rows: unknown[][]): Points {
    const points = [...new Set(rows.map((row) => String(row[0])))].slice(0, MAX_POINTS)
    const valuesByName = new Map<string, Map<string, number | null>>()
    for (const [x, rawName, value] of rows) {
        const name = String(rawName ?? 'None')
        const values = valuesByName.get(name) ?? new Map<string, number | null>()
        values.set(String(x), numberOrNull(value))
        valuesByName.set(name, values)
    }
    const total = (values: (number | null)[]): number => values.reduce<number>((sum, value) => sum + (value ?? 0), 0)
    const series = [...valuesByName].map(([name, values]) => ({
        name,
        values: points.map((point) => values.get(point) ?? null),
    }))
    return {
        points,
        series: series.sort((left, right) => total(right.values) - total(left.values)).slice(0, MAX_BREAKDOWN_SERIES),
    }
}

/** HogQL returns times in the project's timezone, so the labels keep the wall-clock time as written. */
function dateLabels(points: string[]): { labels: string[]; ticks: string[] } | null {
    const dates = points.map((point) => TIMESTAMP.exec(point)?.groups)
    if (dates.some((date) => !date)) {
        return null
    }
    const dayOf = (index: number): string => `${MONTHS[Number(dates[index]!.month) - 1]} ${Number(dates[index]!.day)}`
    const timeOf = (index: number): string => dates[index]!.time ?? '00:00'
    const showTime = dates.some((_, index) => timeOf(index) !== '00:00')

    const labels = points.map((_, index) => (showTime ? `${dayOf(index)} ${timeOf(index)}` : dayOf(index)))
    const ticks = labels.map((label, index) =>
        showTime && index > 0 && dayOf(index - 1) === dayOf(index) ? timeOf(index) : label
    )
    return { labels, ticks }
}

/** Draws SQL rows as a chart, with the first column as the x-axis. */
export function sqlEvidenceChart(columns: string[], rows: unknown[][]): StoryEvidenceChartData | null {
    if (columns.length < 2 || rows.length === 0) {
        return null
    }
    const long = isLongShape(rows)
    const { points, series } = long ? longSeries(rows) : wideSeries(columns, rows)
    if (!series.length) {
        return null
    }
    const dates = dateLabels(points)
    return {
        type: dates ? 'line' : 'bar',
        labels: dates?.labels ?? points,
        ticks: dates?.ticks ?? points,
        series,
        yAxisLabel: long ? columns[2]! : series.length === 1 ? series[0]!.name : null,
    }
}
