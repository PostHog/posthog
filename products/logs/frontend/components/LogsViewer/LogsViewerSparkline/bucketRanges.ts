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
    // A bucket spans its own start to the next one's, so the charted range ends one interval past
    // the last start. Measuring it by that start instead would drop a window sitting inside the
    // final bucket, which is where the newest rows are on the default newest-first view.
    const lastStart = bucketTimesMs[bucketTimesMs.length - 1]
    // A lone bucket has no next start to measure its width from, so treat it as open-ended rather
    // than zero-width — otherwise any window starting after its start (i.e. every row inside it)
    // would fall past `lastStart` and drop the highlight.
    const interval = bucketTimesMs.length > 1 ? bucketTimesMs[1] - bucketTimesMs[0] : Number.POSITIVE_INFINITY
    if (toMs < bucketTimesMs[0] || fromMs > lastStart + interval) {
        return null
    }
    return {
        startIndex: containingBucket(bucketTimesMs, fromMs),
        endIndex: containingBucket(bucketTimesMs, toMs),
    }
}
