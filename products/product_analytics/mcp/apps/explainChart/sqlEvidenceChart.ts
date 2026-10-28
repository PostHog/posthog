import type { StoryEvidenceChartData } from './explainChartTypes'

const MAX_POINTS = 200
const MAX_BREAKDOWN_SERIES = 10
const TIMESTAMP = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function toNumber(value: unknown): number | null {
    return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function isNumericColumn(rows: unknown[][], index: number): boolean {
    return (
        rows.some((row) => toNumber(row[index]) !== null) &&
        rows.every((row) => row[index] === null || toNumber(row[index]) !== null)
    )
}

function unique(values: string[]): string[] {
    return [...new Set(values)]
}

/** HogQL returns times in the project's timezone, so the labels keep the wall-clock time as written. */
function timeLabels(points: string[]): { labels: string[]; ticks: string[] } | null {
    const matches = points.map((point) => TIMESTAMP.exec(point))
    if (matches.some((match) => !match)) {
        return null
    }
    const hasTime = matches.some((match) => match![4] !== undefined && `${match![4]}:${match![5]}` !== '00:00')
    const labels: string[] = []
    const ticks: string[] = []
    matches.forEach((match, index) => {
        const [, , month, day, hour = '00', minute = '00'] = match!
        const date = `${MONTHS[Number(month) - 1]} ${Number(day)}`
        const time = `${hour}:${minute}`
        const sameDay = index > 0 && matches[index - 1]![0].slice(0, 10) === match![0].slice(0, 10)
        labels.push(hasTime ? `${date} ${time}` : date)
        ticks.push(!hasTime ? date : sameDay ? time : `${date} ${time}`)
    })
    return { labels, ticks }
}

/**
 * Draws SQL rows as a chart. The first column is the x-axis. When the second column is text, it breaks the first
 * numeric column after it down into one series per value. Otherwise each numeric column is a series.
 */
export function sqlEvidenceChart(columns: string[], rows: unknown[][]): StoryEvidenceChartData | null {
    if (columns.length < 2 || rows.length === 0) {
        return null
    }
    const xOf = (row: unknown[]): string => String(row[0] ?? '')
    const breakdown = columns.length >= 3 && !isNumericColumn(rows, 1)
    const valueIndexes = columns
        .map((_, index) => index)
        .filter((index) => index > (breakdown ? 1 : 0) && isNumericColumn(rows, index))
    if (!valueIndexes.length) {
        return null
    }

    let points: string[]
    let series: StoryEvidenceChartData['series']
    let yAxisLabel: string | null
    if (breakdown) {
        const valueIndex = valueIndexes[0]!
        const nameOf = (row: unknown[]): string => String(row[1] ?? 'None')
        points = unique(rows.map(xOf)).slice(0, MAX_POINTS)
        const cells = new Map(rows.map((row) => [`${xOf(row)}\u0000${nameOf(row)}`, toNumber(row[valueIndex])]))
        const totals = new Map<string, number>()
        for (const row of rows) {
            totals.set(nameOf(row), (totals.get(nameOf(row)) ?? 0) + (toNumber(row[valueIndex]) ?? 0))
        }
        series = [...totals.keys()]
            .sort((left, right) => totals.get(right)! - totals.get(left)!)
            .slice(0, MAX_BREAKDOWN_SERIES)
            .map((name) => ({ name, values: points.map((point) => cells.get(`${point}\u0000${name}`) ?? null) }))
        yAxisLabel = columns[valueIndex]!
    } else {
        const kept = rows.slice(0, MAX_POINTS)
        points = kept.map(xOf)
        series = valueIndexes.map((index) => ({
            name: columns[index]!,
            values: kept.map((row) => toNumber(row[index])),
        }))
        yAxisLabel = valueIndexes.length === 1 ? columns[valueIndexes[0]!]! : null
    }

    const time = timeLabels(points)
    return {
        type: time ? 'line' : 'bar',
        labels: time?.labels ?? points,
        ticks: time?.ticks ?? points,
        series,
        yAxisLabel,
    }
}
