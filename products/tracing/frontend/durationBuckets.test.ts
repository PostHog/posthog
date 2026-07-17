import {
    bucketUpperBound,
    fillBucketSeries,
    formatBucketLabel,
    pivotDurationHistogram,
    selectionToDurationRange,
    snapDurationToBucket,
    visibleDurationRange,
} from './durationBuckets'

const MS = 1_000_000 // ns per ms

describe('durationBuckets', () => {
    it.each([
        [1_500_000, 1 * MS], // 1.5ms → 1ms
        [3_000_000, 2 * MS], // 3ms → 2ms
        [3_500_000, 2 * MS], // 3.5ms → 2ms
        [700 * MS, 500 * MS], // 700ms → 500ms
        [2 * MS, 2 * MS], // exact bucket value stays put
        [999, 500], // 999ns → 500ns
        [0, 1], // zero durations park in the 1ns bucket
        [5_000_000_000, 5_000_000_000], // exact 5s
    ])('snapDurationToBucket(%i) → %i', (ns, expected) => {
        expect(snapDurationToBucket(ns)).toBe(expected)
    })

    it('fillBucketSeries spans the 1-2-5 series inclusively', () => {
        expect(fillBucketSeries(1 * MS, 500 * MS)).toEqual(
            [1, 2, 5, 10, 20, 50, 100, 200, 500].map((bucketMs) => bucketMs * MS)
        )
        expect(fillBucketSeries(2 * MS, 2 * MS)).toEqual([2 * MS])
    })

    it.each([
        [500, '500ns'],
        [2_000, '2µs'],
        [2 * MS, '2ms'],
        [500 * MS, '500ms'],
        [5_000_000_000, '5s'],
    ])('formatBucketLabel(%i) → %s', (ns, expected) => {
        expect(formatBucketLabel(ns)).toBe(expected)
    })

    it('pivotDurationHistogram stacks services and fills axis gaps with zeros', () => {
        const rows = [
            { bucket_ns: 1 * MS, service: 'web', count: 1 },
            { bucket_ns: 2 * MS, service: 'web', count: 2 },
            // Nothing between 2ms and 500ms — the axis must still be continuous.
            { bucket_ns: 500 * MS, service: 'api', count: 1 },
        ]
        const result = pivotDurationHistogram(rows, ['c1', 'c2'])

        expect(result.bucketsNs).toEqual([1, 2, 5, 10, 20, 50, 100, 200, 500].map((bucketMs) => bucketMs * MS))
        expect(result.labels).toEqual(['1ms', '2ms', '5ms', '10ms', '20ms', '50ms', '100ms', '200ms', '500ms'])
        expect(result.data).toEqual([
            { name: 'api', values: [0, 0, 0, 0, 0, 0, 0, 0, 1], color: 'c1' },
            { name: 'web', values: [1, 2, 0, 0, 0, 0, 0, 0, 0], color: 'c2' },
        ])
    })

    it('pivotDurationHistogram returns empties for no rows', () => {
        expect(pivotDurationHistogram([], ['c1'])).toEqual({ data: [], bucketsNs: [], labels: [] })
    })

    it.each([
        [1, 2],
        [2, 5],
        [5, 10],
        [500 * MS, 1_000 * MS], // 500ms → 1s
        [1_000 * MS, 2_000 * MS],
    ])('bucketUpperBound(%i) → %i', (bucket, expected) => {
        expect(bucketUpperBound(bucket)).toBe(expected)
    })

    // Bucket b covers [b, nextBucket(b)) — an off-by-one here silently shifts which spans a
    // histogram drag-selection matches (the 5ms bar must mean [5ms, 10ms)).
    it.each<[number, number, { minNs: number; maxNs: number } | null]>([
        [0, 1, { minNs: 1 * MS, maxNs: 5 * MS }], // interior selection: max is the bucket after the last bar
        [2, 2, { minNs: 5 * MS, maxNs: 10 * MS }], // single bar
        [2, 3, { minNs: 5 * MS, maxNs: 20 * MS }], // ends on the last bar: upper edge extrapolated on the series
        [3, 99, { minNs: 10 * MS, maxNs: 20 * MS }], // out-of-range end clamps to the last bar
    ])('selectionToDurationRange over [1,2,5,10]ms maps [%i, %i] → %o', (startIndex, endIndex, expected) => {
        const bucketsNs = [1, 2, 5, 10].map((bucketMs) => bucketMs * MS)
        expect(selectionToDurationRange(bucketsNs, startIndex, endIndex)).toEqual(expected)
    })

    it('selectionToDurationRange returns null for an empty axis', () => {
        expect(selectionToDurationRange([], 0, 0)).toBeNull()
    })

    it('visibleDurationRange orders min/max regardless of sort direction and clamps indices', () => {
        const durations = [900, 500, 100] // DESC-sorted list
        expect(visibleDurationRange({ startIndex: 0, stopIndex: 2 }, durations)).toEqual({ minNs: 100, maxNs: 900 })
        // ASC direction: boundary rows reversed, same range comes back ordered.
        expect(visibleDurationRange({ startIndex: 2, stopIndex: 0 }, durations)).toEqual({ minNs: 100, maxNs: 900 })
        // Indices past the end clamp to the last row.
        expect(visibleDurationRange({ startIndex: 1, stopIndex: 99 }, durations)).toEqual({ minNs: 100, maxNs: 500 })
        expect(visibleDurationRange(null, durations)).toBeNull()
        expect(visibleDurationRange({ startIndex: 0, stopIndex: 1 }, [])).toBeNull()
    })
})
