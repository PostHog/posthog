import { trendSeries } from './trends'

describe('trendSeries', () => {
    const buckets = (values: (number | null)[]): { bucket_start: string; value: number | null }[] =>
        values.map((value, index) => ({ bucket_start: `2026-06-0${index + 1}T00:00:00Z`, value }))

    const read = (bucket: { value: number | null }): number | null => bucket.value

    it('is null when nothing was measured, so the card can show its empty state', () => {
        expect(trendSeries(buckets([null, null]), read, 'day')).toBeNull()
        expect(trendSeries([], read, 'day')).toBeNull()
    })

    it('drops leading empty buckets so the delta baselines against a measured value', () => {
        // Without the trim the card would baseline on a zero-filled bucket and report a false rise.
        expect(trendSeries(buckets([null, null, 10, 12]), read, 'day')).toEqual({
            values: [10, 12],
            labels: ['Jun 3', 'Jun 4'],
        })
    })

    it('carries the last value across a gap instead of dipping to zero', () => {
        expect(trendSeries(buckets([10, null, 12]), read, 'day')?.values).toEqual([10, 10, 12])
    })

    it('keeps a measured zero, which is a value rather than a gap', () => {
        expect(trendSeries(buckets([10, 0, 12]), read, 'day')?.values).toEqual([10, 0, 12])
    })

    it('labels hourly buckets with the time', () => {
        expect(trendSeries(buckets([10]), read, 'hour')?.labels).toEqual(['Jun 1 00:00'])
    })
})
