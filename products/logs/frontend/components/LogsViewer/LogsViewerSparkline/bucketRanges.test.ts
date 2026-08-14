import { highlightedBucketRange, selectedDateRange } from './bucketRanges'

// Four buckets a minute apart.
const BUCKETS = [0, 60_000, 120_000, 180_000]
const BUCKET_TIMES = BUCKETS.map((ms) => new Date(ms).toISOString())

describe('bucketRanges', () => {
    it('ends a drag selection at the next bucket, so its last bucket is included', () => {
        // Ending at the selected bucket's own start would cut it out of the results the user just
        // dragged over.
        expect(selectedDateRange(BUCKET_TIMES, 1, 2)).toEqual({
            date_from: BUCKET_TIMES[1],
            date_to: BUCKET_TIMES[3],
        })
    })

    it('leaves a drag selection open-ended when it runs to the final bucket', () => {
        // No bucket follows the last one, and the query reads a missing end as "now".
        expect(selectedDateRange(BUCKET_TIMES, 2, 3)).toEqual({ date_from: BUCKET_TIMES[2], date_to: undefined })
    })

    it('returns no drag selection when it does not start on a charted bucket', () => {
        expect(selectedDateRange(BUCKET_TIMES, 9, 9)).toBeNull()
    })

    it.each([
        // The highlight covers whole bars, so a window starting mid-bucket still includes that bucket.
        ['a window starting mid-bucket', 90_000, 150_000, { startIndex: 1, endIndex: 2 }],
        ['a window on exact bucket starts', 60_000, 120_000, { startIndex: 1, endIndex: 2 }],
        ['a window inside one bucket', 70_000, 80_000, { startIndex: 1, endIndex: 1 }],
        ['a window starting before the first bucket', -50_000, 60_000, { startIndex: 0, endIndex: 1 }],
        ['a window running past the last bucket', 120_000, 999_000, { startIndex: 2, endIndex: 3 }],
        // The rows are listed newest-first when `orderBy` is latest, so the ends can arrive reversed.
        ['a reversed window', 150_000, 90_000, { startIndex: 1, endIndex: 2 }],
    ])('covers the buckets spanned by %s', (_, fromMs, toMs, expected) => {
        expect(highlightedBucketRange(BUCKETS, fromMs, toMs)).toEqual(expected)
    })

    it.each([
        ['no buckets are charted', [], 0, 60_000],
        ['the window ends before the first bucket', BUCKETS, -99_000, -50_000],
        ['the window starts after the last bucket', BUCKETS, 200_000, 300_000],
        ['an end is not a real time', BUCKETS, 0, NaN],
    ])('returns null when %s', (_, buckets, fromMs, toMs) => {
        expect(highlightedBucketRange(buckets, fromMs, toMs)).toBeNull()
    })
})
