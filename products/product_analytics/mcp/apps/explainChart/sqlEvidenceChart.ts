import type { StoryEvidenceChartData } from './explainChartTypes'

type Series = StoryEvidenceChartData['series']

interface Points {
    points: string[]
    series: Series
}

const MAX_BREAKDOWN_SERIES = 10
const TIMESTAMP = /^\d{4}-(?<month>\d{2})-(?<day>\d{2})(?:[T ](?<time>\d{2}:\d{2})(?::(?<seconds>\d{2}))?)?/
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
    const valueColumns = columns.map((_, index) => index).filter((index) => index > 0 && isNumberColumn(rows, index))
    return {
        points: rows.map((row) => String(row[0])),
        series: valueColumns.map((index) => ({
            name: columns[index]!,
            values: rows.map((row) => numberOrNull(row[index])),
        })),
    }
}

/** `hour, browser, failures`: one series per browser, with a gap where a browser has no row for an hour. */
function longSeries(rows: unknown[][]): Points {
    const points = [...new Set(rows.map((row) => String(row[0])))]
    const valuesByName = new Map<string, Map<string, number | null>>()
    const totals = new Map<string, number>()
    for (const [x, rawName, value] of rows) {
        const name = String(rawName ?? 'None')
        const values = valuesByName.get(name) ?? new Map<string, number | null>()
        values.set(String(x), numberOrNull(value))
        valuesByName.set(name, values)
        totals.set(name, (totals.get(name) ?? 0) + (numberOrNull(value) ?? 0))
    }
    const topNames = [...totals]
        .sort(([, left], [, right]) => right - left)
        .slice(0, MAX_BREAKDOWN_SERIES)
        .map(([name]) => name)
    return {
        points,
        series: topNames.map((name) => ({
            name,
            values: points.map((point) => valuesByName.get(name)!.get(point) ?? null),
        })),
    }
}

/** HogQL returns times in the project's timezone, so the labels keep the wall-clock time as written. */
function dateLabels(points: string[]): { labels: string[]; ticks: string[] } | null {
    const dates = points.map((point) => TIMESTAMP.exec(point)?.groups)
    if (dates.some((date) => !date)) {
        return null
    }
    const dayOf = (index: number): string => `${MONTHS[Number(dates[index]!.month) - 1]} ${Number(dates[index]!.day)}`
    const showSeconds = dates.some((date) => (date!.seconds ?? '00') !== '00')
    const timeOf = (index: number): string => {
        const { time = '00:00', seconds = '00' } = dates[index]!
        return showSeconds ? `${time}:${seconds}` : time
    }
    const midnight = showSeconds ? '00:00:00' : '00:00'
    const showTime = dates.some((_, index) => timeOf(index) !== midnight)

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
    // A breakdown draws one number, so a second number column would be dropped without a word.
    if (long && columns.length > 3) {
        return null
    }
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
