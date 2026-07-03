import { dayjs, Dayjs } from 'lib/dayjs'

import type { ObservationLabelDayCountApi } from '../generated/api.schemas'

export interface LabelChartData {
    labels: string[]
    up: number[]
    down: number[]
}

/** Expands the sparse by-day label counts into a contiguous `days`-long window ending today, for charting.
 * Defaults to the UTC day so the window lines up with the server's UTC date buckets. */
export function fillLabelDays(
    byDay: ObservationLabelDayCountApi[],
    days: number,
    today: Dayjs = dayjs.utc()
): LabelChartData {
    const byDate = new Map(byDay.map((entry) => [entry.date, entry]))
    const labels: string[] = []
    const up: number[] = []
    const down: number[] = []
    const start = today.startOf('day').subtract(days - 1, 'day')
    for (let i = 0; i < days; i++) {
        const day = start.add(i, 'day')
        const entry = byDate.get(day.format('YYYY-MM-DD'))
        labels.push(day.format('MMM D'))
        up.push(entry?.up ?? 0)
        down.push(entry?.down ?? 0)
    }
    return { labels, up, down }
}
