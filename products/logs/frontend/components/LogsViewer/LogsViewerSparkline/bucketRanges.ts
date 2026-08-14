import { DateRange } from '~/queries/schema/schema-general'

/**
 * Date range for a drag-selected run of buckets. The end is the *next* bucket's start, which keeps
 * the selection's last bucket inclusive. Returns null when the selection does not start on a charted
 * bucket.
 *
 * Selecting through the final bucket has no next start, and the end is left open as `null` rather
 * than undefined: `utcDateRange` in `logsViewerFiltersLogic` normalizes via `dayjs(date_to)`, which
 * reads undefined as the current time and would freeze the range end at whenever that selector last
 * ran. `null` is invalid to dayjs, so it passes through and the range stays open at "now".
 */
export function selectedDateRange(bucketTimes: string[], startIndex: number, endIndex: number): DateRange | null {
    const dateFrom = bucketTimes[startIndex]
    if (!dateFrom) {
        return null
    }
    return { date_from: dateFrom, date_to: bucketTimes[endIndex + 1] ?? null }
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
 * Returns null when the window misses the charted range entirely. Callers already pass `fromMs <=
 * toMs` (`visibleRowDateRange` normalises the order), so this does not re-sort the ends itself.
 */
export function highlightedBucketRange(
    bucketTimesMs: number[],
    fromMs: number,
    toMs: number
): { startIndex: number; endIndex: number } | null {
    if (bucketTimesMs.length === 0 || !Number.isFinite(fromMs) || !Number.isFinite(toMs)) {
        return null
    }
    if (toMs < bucketTimesMs[0] || fromMs > bucketTimesMs[bucketTimesMs.length - 1]) {
        return null
    }
    return {
        startIndex: containingBucket(bucketTimesMs, fromMs),
        endIndex: containingBucket(bucketTimesMs, toMs),
    }
}
