import { anomalyAxisTickFormatter, anomalyChartData } from './anomalyChartData'

describe('anomalyChartData', () => {
    it('charts from the chart window to the last checked bucket and splits the flags at the flag window', () => {
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
        expect(data?.values).toEqual([NaN, 5, 6, NaN, 40, 7])
        expect(data?.earlierFlaggedIndices).toEqual([1])
        expect(data?.flaggedIndices).toEqual([4])
        expect(data?.flagWindowStartIndex).toEqual(4)
        expect(data?.xDomain).toEqual([Date.parse('2026-10-31T00:00:00Z'), Date.parse('2026-11-05T12:00:00Z')])
    })

    it('keeps daily buckets on local midnight when the clocks change in the range', () => {
        const data = anomalyChartData(
            { interval: 'day', scored_through: '2026-11-03T00:00:00-05:00' },
            [
                { bucket_start: '2026-10-31T00:00:00-04:00', value: 1, flag: false },
                { bucket_start: '2026-11-01T00:00:00-04:00', value: 2, flag: true },
                { bucket_start: '2026-11-03T00:00:00-05:00', value: 3, flag: false },
            ],
            {
                chartFrom: '2026-10-31T00:00:00-04:00',
                flagFrom: '2026-11-01T00:00:00-04:00',
                dateTo: '2026-11-04T00:00:00-05:00',
            },
            'America/New_York'
        )

        expect(data?.values).toEqual([1, 2, NaN, 3])
        expect(data?.labels[2]).toEqual('2026-11-02T00:00:00-05:00')
        expect(data?.flaggedIndices).toEqual([1])
    })

    it.each([
        ['day', 'America/New_York', ['Nov 15', null, 'Nov 17']],
        ['hour', 'UTC', ['Nov 15, 05:00', null, 'Nov 17, 05:00']],
    ] as const)('labels only the first and last bucket of a %s axis', (interval, timezone, expected) => {
        const labels = ['2026-11-15T00:00:00-05:00', '2026-11-16T00:00:00-05:00', '2026-11-17T00:00:00-05:00']
        const format = anomalyAxisTickFormatter(interval, timezone, labels.length)

        expect(labels.map((label, index) => format(label, index))).toEqual(expected)
    })
})
