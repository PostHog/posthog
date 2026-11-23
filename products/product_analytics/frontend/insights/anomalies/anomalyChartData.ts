import { Dayjs, dayjs } from 'lib/dayjs'

import type { AnomalySeriesApi, AnomalySeriesPointApi } from 'products/signals/frontend/generated/api.schemas'

export interface AnomalyChartWindow {
    // The start of the chart window. The chart starts at the first bucket on or after it.
    chartFrom: string
    // The start of the flag window.
    flagFrom: string
    dateTo: string
}

export interface AnomalyChartData {
    // ISO bucket starts, oldest first, one per checked bucket of the chart.
    labels: string[]
    // NaN where the bucket has no scored value.
    values: number[]
    // Flagged buckets in the flag window, which put the series in the list.
    flaggedIndices: number[]
    // Flagged buckets before the flag window.
    earlierFlaggedIndices: number[]
    // The first bucket of the flag window, or null when no bucket of the chart is in it.
    flagWindowStartIndex: number | null
    // The x-axis span in epoch ms. It ends half a bucket after the last bucket, so the last bucket is as wide as the others.
    xDomain: [number, number]
}

type ChartSeries = Pick<AnomalySeriesApi, 'interval' | 'scored_through'>

// `add` on a dayjs object in a timezone keeps its UTC offset, so after a daylight saving change a daily step lands
// an hour off midnight. Re-reading the wall time in the timezone keeps daily and longer buckets on local midnight.
// An hour is a fixed length, so hourly steps stay in absolute time.
function stepBucket(bucket: Dayjs, steps: number, unit: ChartSeries['interval'], timezone: string): Dayjs {
    const next = bucket.add(steps, unit)
    return unit === 'hour' ? next : next.tz(timezone, true)
}

// The bucket starts of the chart, oldest first. The grid ends at the last checked bucket, so the chart has no
// unchecked tail.
function bucketGrid(
    series: ChartSeries,
    points: AnomalySeriesPointApi[],
    chartFrom: string,
    dateTo: string,
    timezone: string
): Dayjs[] {
    const unit = series.interval
    const step = (bucket: Dayjs, steps: number): Dayjs => stepBucket(bucket, steps, unit, timezone)
    const anchor = dayjs(points[0].bucket_start).tz(timezone)
    const windowStart = dayjs(chartFrom)
    const windowEnd = dayjs(dateTo)
    const lastPoint = dayjs(points[points.length - 1].bucket_start)
    const lastChecked = series.scored_through ? dayjs(series.scored_through) : lastPoint

    let start = anchor
    while (!step(start, -1).isBefore(windowStart)) {
        start = step(start, -1)
    }
    const starts: Dayjs[] = []
    for (
        let bucket = start;
        !bucket.isAfter(lastChecked) && !step(bucket, 1).isAfter(windowEnd);
        bucket = step(bucket, 1)
    ) {
        starts.push(bucket)
    }
    while (starts.length === 0 || starts[starts.length - 1].isBefore(lastPoint)) {
        // The API can return a bucket the grid does not reach, for example when the clocks moved. Keep it charted.
        starts.push(starts.length ? step(starts[starts.length - 1], 1) : anchor)
    }
    return starts
}

// The grid index of each point, or -1 for a point older than the grid. A daylight saving shift moves a bucket start
// by an hour, so each point lands in the bucket that contains it rather than matching on exact timestamps.
function pointSlots(grid: Dayjs[], points: AnomalySeriesPointApi[]): number[] {
    let slot = 0
    return points.map((point) => {
        const pointStart = dayjs(point.bucket_start)
        while (slot + 1 < grid.length && !grid[slot + 1].isAfter(pointStart)) {
            slot++
        }
        return grid[slot].isAfter(pointStart) ? -1 : slot
    })
}

/**
 * Lays the scored points of a series on a grid of its buckets, so gaps show on the chart.
 *
 * The grid steps from the first point by the series interval. It reaches back to the start of the chart window, and
 * forward to the last checked bucket (`scored_through`) that ends by `dateTo`. Returns null when the series has no
 * points to chart.
 */
export function anomalyChartData(
    series: ChartSeries,
    points: AnomalySeriesPointApi[],
    window: AnomalyChartWindow,
    timezone: string
): AnomalyChartData | null {
    if (points.length === 0) {
        return null
    }
    const grid = bucketGrid(series, points, window.chartFrom, window.dateTo, timezone)
    const flagFrom = dayjs(window.flagFrom)
    const labels = grid.map((bucket) => bucket.format())
    const values = grid.map(() => NaN)
    const flaggedIndices: number[] = []
    const earlierFlaggedIndices: number[] = []
    pointSlots(grid, points).forEach((slot, index) => {
        if (slot === -1) {
            return
        }
        const point = points[index]
        labels[slot] = point.bucket_start
        values[slot] = point.value ?? NaN
        if (!point.flag || point.value == null) {
            return
        }
        if (dayjs(point.bucket_start).isBefore(flagFrom)) {
            earlierFlaggedIndices.push(slot)
        } else {
            flaggedIndices.push(slot)
        }
    })
    const flagWindowStartIndex = grid.findIndex((bucket) => !bucket.isBefore(flagFrom))
    const lastStart = dayjs(labels[labels.length - 1]).tz(timezone)
    const lastEnd = stepBucket(lastStart, 1, series.interval, timezone)

    return {
        labels,
        values,
        flaggedIndices,
        earlierFlaggedIndices,
        flagWindowStartIndex: flagWindowStartIndex === -1 ? null : flagWindowStartIndex,
        xDomain: [dayjs(labels[0]).valueOf(), lastStart.valueOf() + lastEnd.diff(lastStart) / 2],
    }
}

/**
 * Daily ticks label each Monday only. The default axis drops labels that overlap from left to right, so which days
 * keep a label changed with the chart width and the first bucket. A fixed weekday gives every daily row the same
 * ticks, and a week apart is the weekly pattern a daily chart shows.
 */
export function anomalyAxisTickFormatter(
    interval: ChartSeries['interval'],
    timezone: string
): ((label: string) => string | null) | undefined {
    if (interval !== 'day') {
        return undefined
    }
    return (label) => {
        const date = dayjs(label).tz(timezone)
        return date.day() === 1 ? date.format('MMM D') : null
    }
}
