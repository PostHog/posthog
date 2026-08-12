import { dayjs } from 'lib/dayjs'

/** A sparkline's plot: one value per label, oldest first, with no gaps left in either. */
export interface TrendSeries {
    values: number[]
    labels: string[]
}

/** The API's bucketed series shape: oldest first, one bucket per interval across the window. */
interface Bucketed {
    bucket_start: string
}

/**
 * A bucketed API series as a `TrendCard` plot, or null when no bucket carries a value — the card
 * then shows its own empty state instead of a flat line.
 *
 * Empty buckets are a gap in the measurement ("nothing merged", "no run to time"), never a zero, so
 * the two ways a gap can appear are both handled here rather than per metric: leading empty buckets
 * are dropped, so the line opens on real data and the card's delta baselines against a real value,
 * and a later gap carries the last known value forward instead of dipping to zero.
 */
export function trendSeries<T extends Bucketed>(
    buckets: T[],
    value: (bucket: T) => number | null | undefined,
    granularity: string | undefined
): TrendSeries | null {
    const firstMeasured = buckets.findIndex((bucket) => value(bucket) != null)
    if (firstMeasured === -1) {
        return null
    }
    const labelFormat = granularity === 'hour' ? 'MMM D HH:mm' : 'MMM D'
    const series: TrendSeries = { values: [], labels: [] }
    let carried = 0
    for (const bucket of buckets.slice(firstMeasured)) {
        carried = value(bucket) ?? carried
        series.values.push(carried)
        series.labels.push(dayjs(bucket.bucket_start).format(labelFormat))
    }
    return series
}
