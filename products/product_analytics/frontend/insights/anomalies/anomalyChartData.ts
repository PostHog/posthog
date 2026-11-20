import { Dayjs, dayjs } from 'lib/dayjs'

import type { AnomalySeriesApi, AnomalySeriesPointApi } from 'products/signals/frontend/generated/api.schemas'

export interface AnomalyChartWindow {
    // The start of the chart window. The chart starts at the first bucket on or after it.
    chartFrom: string
    // The start of the flag window, which ends at the right edge of the chart.
    flagFrom: string
    dateTo: string
}

export interface AnomalyChartData {
    // ISO bucket starts, oldest first, one per completed bucket of the chart.
    labels: string[]
    // NaN where the bucket has no scored value.
    values: number[]
    // Flagged buckets in the flag window, which put the series in the list.
    flaggedIndices: number[]
    // Flagged buckets before the flag window.
    earlierFlaggedIndices: number[]
    // The first bucket of the flag window, or null when no bucket of the chart is in it.
    flagWindowStartIndex: number | null
    // The first bucket after `scored_through`, or null when every bucket was checked.
    firstUncheckedIndex: number | null
}

type ChartSeries = Pick<AnomalySeriesApi, 'interval' | 'scored_through'>

// The bucket starts of the chart, oldest first.
function bucketGrid(
    series: ChartSeries,
    points: AnomalySeriesPointApi[],
    chartFrom: string,
    dateTo: string,
    timezone: string
): Dayjs[] {
    const unit = series.interval
    const anchor = dayjs(points[0].bucket_start).tz(timezone)
    const windowStart = dayjs(chartFrom)
    const windowEnd = dayjs(dateTo)

    let start = anchor
    while (!start.subtract(1, unit).isBefore(windowStart)) {
        start = start.subtract(1, unit)
    }
    const starts: Dayjs[] = []
    for (let bucket = start; !bucket.add(1, unit).isAfter(windowEnd); bucket = bucket.add(1, unit)) {
        starts.push(bucket)
    }
    const lastPoint = dayjs(points[points.length - 1].bucket_start)
    while (starts.length === 0 || starts[starts.length - 1].isBefore(lastPoint)) {
        // The API can return a bucket the grid does not reach, for example when the clocks moved. Keep it charted.
        starts.push(starts.length ? starts[starts.length - 1].add(1, unit) : anchor)
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
 * The grid steps from the first point by the series interval. It reaches back to the start of the chart window, and
 * forward to the last bucket that ends by `dateTo`. Returns null when the series has no points to chart.
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

    return {
        labels,
        values,
        flaggedIndices,
        earlierFlaggedIndices,
        flagWindowStartIndex: flagWindowStartIndex === -1 ? null : flagWindowStartIndex,
        firstUncheckedIndex: firstUncheckedIndex(grid, series.scored_through),
    }
}
