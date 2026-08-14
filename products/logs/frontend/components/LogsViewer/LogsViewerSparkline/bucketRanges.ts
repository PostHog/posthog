import { DateRange } from '~/queries/schema/schema-general'

/**
 * Date range for a drag-selected run of buckets. The end is the *next* bucket's start, which keeps
 * the selection's last bucket inclusive. Past the final bucket that start does not exist, and the
 * resulting undefined `date_to` is what the query reads as "now". Returns null when the selection
 * does not start on a charted bucket.
 */
export function selectedDateRange(bucketTimes: string[], startIndex: number, endIndex: number): DateRange | null {
    const dateFrom = bucketTimes[startIndex]
    if (!dateFrom) {
        return null
    }
    return { date_from: dateFrom, date_to: bucketTimes[endIndex + 1] }
}

/** Index of the last bucket starting at or before `ms`. Assumes ascending bucket times. */
function containingBucket(bucketTimesMs: number[], ms: number): number {
    let index = 0
    while (index + 1 < bucketTimesMs.length && bucketTimesMs[index + 1] <= ms) {
        index++
    }
    return index
}

/**
 * Maps the continuous time window covered by the visible log rows onto the bucket indices the chart
 * should highlight. The highlight spans whole bars, so each end snaps to the bucket containing it
 * rather than to a fraction of one — a window inside a single bucket highlights that one bucket.
 * Returns null when the window misses the charted range entirely.
 */
export function highlightedBucketRange(
    bucketTimesMs: number[],
    fromMs: number,
    toMs: number
): { startIndex: number; endIndex: number } | null {
    if (bucketTimesMs.length === 0 || !Number.isFinite(fromMs) || !Number.isFinite(toMs)) {
        return null
    }
    const [earlier, later] = fromMs <= toMs ? [fromMs, toMs] : [toMs, fromMs]
    if (later < bucketTimesMs[0] || earlier > bucketTimesMs[bucketTimesMs.length - 1]) {
        return null
    }
    return {
        startIndex: containingBucket(bucketTimesMs, earlier),
        endIndex: containingBucket(bucketTimesMs, later),
    }
}
