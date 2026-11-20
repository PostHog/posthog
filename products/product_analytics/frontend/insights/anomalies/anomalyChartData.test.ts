import { anomalyChartData } from './anomalyChartData'

describe('anomalyChartData', () => {
    it('charts the whole chart window and splits the flags at the start of the flag window', () => {
        const data = anomalyChartData(
            { interval: 'day', scored_through: '2026-11-05T00:00:00+00:00' },
            [
                { bucket_start: '2026-11-01T00:00:00+00:00', value: 5, flag: true },
                { bucket_start: '2026-11-02T00:00:00+00:00', value: 6, flag: false },
                { bucket_start: '2026-11-04T00:00:00+00:00', value: 40, flag: true },
                { bucket_start: '2026-11-05T00:00:00+00:00', value: 7, flag: false },
            ],
            {
                chartFrom: '2026-10-30T12:00:00+00:00',
                flagFrom: '2026-11-03T12:00:00+00:00',
                dateTo: '2026-11-07T06:00:00+00:00',
            },
            'UTC'
        )

        expect(data?.labels[0]).toEqual('2026-10-31T00:00:00Z')
        expect(data?.values).toEqual([NaN, 5, 6, NaN, 40, 7, NaN])
        expect(data?.earlierFlaggedIndices).toEqual([1])
        expect(data?.flaggedIndices).toEqual([4])
        expect(data?.flagWindowStartIndex).toEqual(4)
        expect(data?.firstUncheckedIndex).toEqual(6)
    })

    it('keeps every daily point when the clocks change in the range', () => {
        const data = anomalyChartData(
            { interval: 'day', scored_through: '2026-11-02T00:00:00-05:00' },
            [
                { bucket_start: '2026-10-31T00:00:00-04:00', value: 1, flag: false },
                { bucket_start: '2026-11-01T00:00:00-04:00', value: 2, flag: true },
                { bucket_start: '2026-11-02T00:00:00-05:00', value: 3, flag: false },
            ],
            {
                chartFrom: '2026-10-31T00:00:00-04:00',
                flagFrom: '2026-11-01T00:00:00-04:00',
                dateTo: '2026-11-03T00:00:00-05:00',
            },
            'America/New_York'
        )

        expect(data?.values).toEqual([1, 2, 3])
        expect(data?.flaggedIndices).toEqual([1])
    })
})
