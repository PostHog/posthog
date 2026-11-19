import { anomalyChartData } from './anomalyChartData'

describe('anomalyChartData', () => {
    it('keeps unscored buckets as gaps and marks the flagged and unchecked buckets', () => {
        const data = anomalyChartData(
            {
                interval: 'day',
                scored_buckets: 2,
                scored_through: '2026-11-03T00:00:00+00:00',
                points: [
                    { bucket_start: '2026-11-01T00:00:00+00:00', value: 5, flag: false },
                    { bucket_start: '2026-11-03T00:00:00+00:00', value: 40, flag: true },
                ],
            },
            '2026-11-01T00:00:00+00:00',
            '2026-11-06T06:00:00+00:00',
            'UTC'
        )

        expect(data?.labels).toHaveLength(5)
        expect(data?.values).toEqual([5, NaN, 40, NaN, NaN])
        expect(data?.flaggedIndices).toEqual([2])
        expect(data?.firstUncheckedIndex).toEqual(3)
    })

    it('starts at the first point when the API capped the older points', () => {
        const data = anomalyChartData(
            {
                interval: 'day',
                scored_buckets: 10,
                scored_through: '2026-11-05T00:00:00+00:00',
                points: [
                    { bucket_start: '2026-11-04T00:00:00+00:00', value: 1, flag: false },
                    { bucket_start: '2026-11-05T00:00:00+00:00', value: 2, flag: false },
                ],
            },
            '2026-10-01T00:00:00+00:00',
            '2026-11-06T00:00:00+00:00',
            'UTC'
        )

        expect(data?.values).toEqual([1, 2])
        expect(data?.firstUncheckedIndex).toBeNull()
    })

    it('keeps every daily point when the clocks change in the range', () => {
        const data = anomalyChartData(
            {
                interval: 'day',
                scored_buckets: 3,
                scored_through: '2026-11-02T00:00:00-05:00',
                points: [
                    { bucket_start: '2026-10-31T00:00:00-04:00', value: 1, flag: false },
                    { bucket_start: '2026-11-01T00:00:00-04:00', value: 2, flag: true },
                    { bucket_start: '2026-11-02T00:00:00-05:00', value: 3, flag: false },
                ],
            },
            '2026-10-31T00:00:00-04:00',
            '2026-11-03T00:00:00-05:00',
            'America/New_York'
        )

        expect(data?.values).toEqual([1, 2, 3])
        expect(data?.flaggedIndices).toEqual([1])
    })
})
