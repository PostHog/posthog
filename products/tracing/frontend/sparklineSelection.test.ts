import { bucketRangeToDateRange } from './sparklineSelection'

const DATES = ['2024-01-01T00:00:00.000Z', '2024-01-01T01:00:00.000Z', '2024-01-01T02:00:00.000Z']

describe('bucketRangeToDateRange', () => {
    it('ends the range on the start of the bucket after the last selected one', () => {
        expect(bucketRangeToDateRange(DATES, 0, 1)).toEqual({ date_from: DATES[0], date_to: DATES[2] })
    })

    it('falls back to the queried end when the selection reaches the last bucket', () => {
        const currentDateTo = '2024-01-01T02:30:00.000Z'
        expect(bucketRangeToDateRange(DATES, 1, 2, currentDateTo)).toEqual({
            date_from: DATES[1],
            date_to: currentDateTo,
        })
    })

    it('leaves a relative window open-ended on the last bucket', () => {
        expect(bucketRangeToDateRange(DATES, 2, 2, null)).toEqual({ date_from: DATES[2], date_to: null })
    })

    it('returns null when the selection starts past the rendered buckets', () => {
        expect(bucketRangeToDateRange(DATES, 3, 4)).toBeNull()
    })
})
