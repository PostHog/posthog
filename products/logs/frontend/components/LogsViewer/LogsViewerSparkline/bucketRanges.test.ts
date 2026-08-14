import { highlightedBucketRange, selectedDateRange } from './bucketRanges'

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
        // Null, not undefined: `utcDateRange` normalizes with `dayjs(date_to)`, which reads undefined
        // as the current time and would pin the end instead of leaving the range open at "now".
        expect(selectedDateRange(BUCKET_TIMES, 2, 3)).toEqual({ date_from: BUCKET_TIMES[2], date_to: null })
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
        ['a window ending exactly at the last bucket', 180_000, 999_000, { startIndex: 3, endIndex: 3 }],
        ['a window starting exactly at the first bucket', 0, 30_000, { startIndex: 0, endIndex: 0 }],
    ])('covers the buckets spanned by %s', (_, fromMs, toMs, expected) => {
        expect(highlightedBucketRange(BUCKETS, fromMs, toMs)).toEqual(expected)
    })

    it.each([
        ['no buckets are charted', [], 0, 60_000],
        ['the window ends before the first bucket', BUCKETS, -99_000, -50_000],
        ['the window starts after the last bucket', BUCKETS, 200_000, 300_000],
        ['an end is not a real time', BUCKETS, 0, NaN],
        ['the start is not a real time', BUCKETS, NaN, 60_000],
    ])('returns null when %s', (_, buckets, fromMs, toMs) => {
        expect(highlightedBucketRange(buckets, fromMs, toMs)).toBeNull()
    })
})
