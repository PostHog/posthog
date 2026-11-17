import { Dayjs, dayjs } from 'lib/dayjs'

import type { AnomalySeriesApi } from 'products/signals/frontend/generated/api.schemas'

// Bounds the canvas work for long hourly ranges. Older buckets drop off the left edge.
const MAX_BUCKETS = 1000

export interface AnomalyChartData {
    // ISO bucket starts, oldest first, one per completed bucket of the chart.
    labels: string[]
    // NaN where the bucket has no scored value.
    values: number[]
    flaggedIndices: number[]
    // The first bucket after `scored_through`, or null when every bucket was checked.
    firstUncheckedIndex: number | null
}

/**
 * Lays the scored points of a series on a grid of its buckets, so gaps and the unchecked tail show on the chart.
 *
 * The grid steps from the first point by the series interval. It reaches back to `dateFrom` unless the API capped the
 * points, and forward to the last bucket that ends by `dateTo`. Returns null when the series has no points to chart.
 */
export function anomalyChartData(
    series: Pick<AnomalySeriesApi, 'interval' | 'points' | 'scored_buckets' | 'scored_through'>,
    dateFrom: string,
    dateTo: string,
    timezone: string
): AnomalyChartData | null {
    const points = series.points ?? []
    if (points.length === 0) {
        return null
    }
    const unit = series.interval
    const anchor = dayjs(points[0].bucket_start).tz(timezone)
    const rangeStart = dayjs(dateFrom)
    const rangeEnd = dayjs(dateTo)

    let start = anchor
    // Fewer points than scored buckets means the API left the oldest ones out, so the chart starts at the first point.
    if (points.length >= series.scored_buckets) {
        while (!start.subtract(1, unit).isBefore(rangeStart)) {
            start = start.subtract(1, unit)
        }
    }
    const starts: Dayjs[] = []
    for (let bucket = start; !bucket.add(1, unit).isAfter(rangeEnd); bucket = bucket.add(1, unit)) {
        starts.push(bucket)
    }
    const lastPoint = dayjs(points[points.length - 1].bucket_start)
    while (starts.length === 0 || starts[starts.length - 1].isBefore(lastPoint)) {
        // The API can return a bucket the grid does not reach, for example when the clocks moved. Keep it charted.
        starts.push(starts.length ? starts[starts.length - 1].add(1, unit) : anchor)
    }
    const grid = starts.slice(-MAX_BUCKETS)

    const labels = grid.map((bucket) => bucket.format())
    const values = grid.map(() => NaN)
    const flaggedIndices: number[] = []
    // Each point lands in the bucket that contains it. A daylight saving shift moves a bucket start by an hour,
    // so matching on exact timestamps would drop points.
    let slot = 0
    for (const point of points) {
        const pointStart = dayjs(point.bucket_start)
        while (slot + 1 < grid.length && !grid[slot + 1].isAfter(pointStart)) {
            slot++
        }
        if (grid[slot].isAfter(pointStart)) {
            continue
        }
        labels[slot] = point.bucket_start
        values[slot] = point.value ?? NaN
        if (point.flag && point.value != null) {
            flaggedIndices.push(slot)
        }
    }

    let firstUncheckedIndex: number | null = null
    if (series.scored_through) {
        const scoredThrough = dayjs(series.scored_through)
        const index = grid.findIndex((bucket) => bucket.isAfter(scoredThrough))
        firstUncheckedIndex = index === -1 ? null : index
    }

    return { labels, values, flaggedIndices, firstUncheckedIndex }
}
