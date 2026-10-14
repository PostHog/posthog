import { parseBucketStart } from '@/lib/dates'
import type { MetricInterval, MetricSeries, MetricSnapshot } from '@/model/types'
import type { ChartPoint } from '@/ui/chart/types'

const HOUR_MS = 3_600_000

export function seriesChartPoints(series: MetricSeries): ChartPoint[] {
    return series.points
        .map((point) => ({ at: parseBucketStart(point.at), value: point.value }))
        .filter((point) => Number.isFinite(point.at))
}

function stepBack(end: Date, interval: MetricInterval, steps: number): number {
    switch (interval) {
        case 'hour':
            return end.getTime() - steps * HOUR_MS
        case 'day':
        case 'week': {
            const days = interval === 'week' ? 7 * steps : steps
            const date = new Date(end)
            date.setDate(date.getDate() - days)
            return date.getTime()
        }
        case 'month': {
            const date = new Date(end)
            date.setMonth(date.getMonth() - steps)
            return date.getTime()
        }
    }
}

/**
 * The saved series has no dates, only trailing buckets. They are placed one interval apart, the last at the time the
 * value was measured, so the axis and the tooltip show roughly where each bucket falls.
 */
export function snapshotChartPoints(snapshot: MetricSnapshot, interval: MetricInterval, now: Date): ChartPoint[] {
    const measured = snapshot.at ? Date.parse(snapshot.at) : Number.NaN
    const end = Number.isFinite(measured) ? new Date(measured) : now
    const last = snapshot.series.length - 1
    return snapshot.series.map((value, index) => ({ at: stepBack(end, interval, last - index), value }))
}
