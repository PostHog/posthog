// Pure helpers for the duration-histogram sparkline (JON-36). The list sorted by duration pairs
// with a histogram of trace counts per logarithmic duration bucket; everything here is pure so it
// can be unit-tested without the kea logic's import graph.

export interface DurationHistogramRow {
    bucket_ns: number
    service: string
    count: number
}

export interface TracingDurationHistogramData {
    data: { name: string; values: number[]; color: string }[]
    /** The 1-2-5 series bucket for each bar, in ns — the duration-space sibling of `dates`. */
    bucketsNs: number[]
    labels: string[]
}

export interface VisibleDurationRange {
    minNs: number
    maxNs: number
}

const BUCKET_MANTISSAS = [1, 2, 5]

/**
 * Snap a duration (ns) down onto the 1-2-5 log series the histogram buckets use (1ms, 2ms, 5ms, ...).
 *
 * Mirrors the SQL bucketing in `backend/duration_histogram_query_runner.py` — the backend buckets
 * authoritatively; the frontend only re-snaps to map the visible rows' durations (scroll position is
 * client-side) onto the rendered axis. Change the series in BOTH places or the highlight drifts.
 */
export function snapDurationToBucket(ns: number): number {
    const clamped = Math.max(ns, 1)
    const decade = Math.pow(10, Math.floor(Math.log10(clamped)))
    const mantissa = clamped / decade
    return Math.round(decade * (mantissa < 2 ? 1 : mantissa < 5 ? 2 : 5))
}

/** Every 1-2-5 series bucket from minBucket to maxBucket inclusive (both already snapped). */
export function fillBucketSeries(minBucket: number, maxBucket: number): number[] {
    const buckets: number[] = []
    let decade = Math.pow(10, Math.floor(Math.log10(Math.max(minBucket, 1))))
    for (;;) {
        for (const mantissa of BUCKET_MANTISSAS) {
            const bucket = Math.round(decade * mantissa)
            if (bucket > maxBucket) {
                return buckets
            }
            if (bucket >= minBucket) {
                buckets.push(bucket)
            }
        }
        decade *= 10
    }
}

/** Buckets are exact 1-2-5 values, so labels stay clean integers ("2ms", "500ms", "1s"). */
export function formatBucketLabel(ns: number): string {
    if (ns < 1_000) {
        return `${ns}ns`
    }
    if (ns < 1_000_000) {
        return `${ns / 1_000}µs`
    }
    if (ns < 1_000_000_000) {
        return `${ns / 1_000_000}ms`
    }
    return `${ns / 1_000_000_000}s`
}

/**
 * Pivot histogram rows into the Sparkline series shape, filling gaps along the 1-2-5 series
 * between the smallest and largest non-empty bucket so the log axis is continuous.
 */
export function pivotDurationHistogram(
    rows: DurationHistogramRow[],
    colors: readonly string[]
): TracingDurationHistogramData {
    if (!rows.length) {
        return { data: [], bucketsNs: [], labels: [] }
    }

    const minBucket = Math.min(...rows.map((row) => row.bucket_ns))
    const maxBucket = Math.max(...rows.map((row) => row.bucket_ns))
    const bucketsNs = fillBucketSeries(minBucket, maxBucket)
    const indexByBucket = new Map(bucketsNs.map((bucket, index) => [bucket, index]))

    const accumulated: Record<string, number[]> = {}
    for (const row of rows) {
        if (!row.service) {
            continue
        }
        const index = indexByBucket.get(row.bucket_ns)
        if (index === undefined) {
            continue
        }
        if (!accumulated[row.service]) {
            accumulated[row.service] = bucketsNs.map(() => 0)
        }
        accumulated[row.service][index] += row.count
    }

    const data = Object.entries(accumulated)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([name, values], index) => ({
            name,
            values,
            color: colors[index % colors.length],
        }))
        .filter((series) => series.values.reduce((a, b) => a + b, 0) > 0)

    return { data, bucketsNs, labels: bucketsNs.map(formatBucketLabel) }
}

/**
 * Duration range spanned by the visible slice of a duration-sorted list, given the durations of
 * its rows in display order. Returns min/max regardless of ASC/DESC sort direction.
 */
export function visibleDurationRange(
    visibleRowRange: { startIndex: number; stopIndex: number } | null,
    durationsNs: number[]
): VisibleDurationRange | null {
    if (!visibleRowRange || durationsNs.length === 0) {
        return null
    }
    const startIndex = Math.max(0, Math.min(visibleRowRange.startIndex, durationsNs.length - 1))
    const stopIndex = Math.max(0, Math.min(visibleRowRange.stopIndex, durationsNs.length - 1))
    const a = durationsNs[startIndex]
    const b = durationsNs[stopIndex]
    if (a === undefined || b === undefined) {
        return null
    }
    return { minNs: Math.min(a, b), maxNs: Math.max(a, b) }
}
