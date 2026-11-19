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

type ChartSeries = Pick<AnomalySeriesApi, 'interval' | 'points' | 'scored_buckets' | 'scored_through'>
type SeriesPoint = NonNullable<AnomalySeriesApi['points']>[number]

// The bucket starts of the chart, oldest first.
function bucketGrid(
    series: ChartSeries,
    points: SeriesPoint[],
    dateFrom: string,
    dateTo: string,
    timezone: string
): Dayjs[] {
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
    return starts.slice(-MAX_BUCKETS)
}

// The grid index of each point, or -1 for a point older than the grid. A daylight saving shift moves a bucket start
// by an hour, so each point lands in the bucket that contains it rather than matching on exact timestamps.
function pointSlots(grid: Dayjs[], points: SeriesPoint[]): number[] {
    let slot = 0
    return points.map((point) => {
        const pointStart = dayjs(point.bucket_start)
        while (slot + 1 < grid.length && !grid[slot + 1].isAfter(pointStart)) {
            slot++
        }
        return grid[slot].isAfter(pointStart) ? -1 : slot
    })
}

function firstUncheckedIndex(grid: Dayjs[], scoredThrough: string | null): number | null {
    if (!scoredThrough) {
        return null
    }
    const index = grid.findIndex((bucket) => bucket.isAfter(dayjs(scoredThrough)))
    return index === -1 ? null : index
}

/**
 * Lays the scored points of a series on a grid of its buckets, so gaps and the unchecked tail show on the chart.
 *
 * The grid steps from the first point by the series interval. It reaches back to `dateFrom` unless the API capped the
 * points, and forward to the last bucket that ends by `dateTo`. Returns null when the series has no points to chart.
 */
export function anomalyChartData(
    series: ChartSeries,
    dateFrom: string,
    dateTo: string,
    timezone: string
): AnomalyChartData | null {
    const points = series.points ?? []
    if (points.length === 0) {
        return null
    }
    const grid = bucketGrid(series, points, dateFrom, dateTo, timezone)
    const labels = grid.map((bucket) => bucket.format())
    const values = grid.map(() => NaN)
    const flaggedIndices: number[] = []
    pointSlots(grid, points).forEach((slot, index) => {
        if (slot === -1) {
            return
        }
        const point = points[index]
        labels[slot] = point.bucket_start
        values[slot] = point.value ?? NaN
        if (point.flag && point.value != null) {
            flaggedIndices.push(slot)
        }
    })

    return { labels, values, flaggedIndices, firstUncheckedIndex: firstUncheckedIndex(grid, series.scored_through) }
}
