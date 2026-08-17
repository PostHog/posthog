import { DateRange } from '~/queries/schema/schema-general'

/**
 * The end is the *next* bucket's start, so the selection's last bucket stays inclusive.
 *
 * Past the final bucket the end must be `null`, not undefined: `utcDateRange` in
 * `logsViewerFiltersLogic` normalizes via `dayjs(date_to)`, which reads undefined as the current
 * time and would freeze the end there. `null` is invalid to dayjs, so the range stays open at "now".
 */
export function selectedDateRange(bucketTimes: string[], startIndex: number, endIndex: number): DateRange | null {
    const dateFrom = bucketTimes[startIndex]
    if (!dateFrom) {
        return null
    }
    return { date_from: dateFrom, date_to: bucketTimes[endIndex + 1] ?? null }
}

/** Assumes ascending bucket times. */
function containingBucket(bucketTimesMs: number[], ms: number): number {
    let index = 0
    while (index + 1 < bucketTimesMs.length && bucketTimesMs[index + 1] <= ms) {
        index++
    }
    return index
}

/**
 * Each end snaps to the bucket containing it, so the highlight covers whole bars. Callers already
 * pass `fromMs <= toMs` (`visibleRowDateRange` normalises the order), so the ends are not re-sorted.
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
