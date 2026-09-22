import { highlightedBucketRange, selectedDateRange } from './bucketRanges'

const BUCKETS = [0, 60_000, 120_000, 180_000]
const BUCKET_TIMES = BUCKETS.map((ms) => new Date(ms).toISOString())

describe('bucketRanges', () => {
    it('ends a drag selection at the next bucket, so its last bucket is included', () => {
        expect(selectedDateRange(BUCKET_TIMES, 1, 2)).toEqual({
            date_from: BUCKET_TIMES[1],
            date_to: BUCKET_TIMES[3],
        })
    })

    it('leaves a drag selection open-ended when it runs to the final bucket', () => {
        expect(selectedDateRange(BUCKET_TIMES, 2, 3)).toEqual({ date_from: BUCKET_TIMES[2], date_to: null })
    })

    it('snaps a highlight out to whole buckets', () => {
        expect(highlightedBucketRange(BUCKETS, 90_000, 150_000)).toEqual({ startIndex: 1, endIndex: 2 })
    })

    it('highlights the final bucket for a window inside it', () => {
        expect(highlightedBucketRange(BUCKETS, 190_000, 200_000)).toEqual({ startIndex: 3, endIndex: 3 })
    })

    it('highlights a lone bucket for a window starting after its start (open-ended width)', () => {
        expect(highlightedBucketRange([60_000], 90_000, 150_000)).toEqual({ startIndex: 0, endIndex: 0 })
    })
})
