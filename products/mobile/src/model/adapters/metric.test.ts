import { downsample, formatMetricValue, hotBars, metricView } from './metric'

const hotIndexes = (values: number[]): number[] => hotBars(values).flatMap((hot, index) => (hot ? [index] : []))

describe('report metric', () => {
    test('downsamples a long series to at most 14 bars and keeps short ones', () => {
        const long = Array.from({ length: 30 }, (_, index) => index)
        const bars = downsample(long)
        expect(bars).toHaveLength(14)
        expect(bars[0]).toBe(0.5)
        expect(bars[13]).toBe(28)
        expect(downsample([1, 2, 3])).toEqual([1, 2, 3])
    })

    test.each<[string, number[], number[]]>([
        [
            'spike that keeps going',
            [3, 2, 4, 3, 2, 3, 48, 76, 92, 104, 98, 112, 120, 110],
            [6, 7, 8, 9, 10, 11, 12, 13],
        ],
        ['drop to zero', [96, 104, 88, 110, 92, 100, 98, 2, 2, 2, 2, 2, 2, 2], [7, 8, 9, 10, 11, 12, 13]],
        ['spike that recovered', [2, 2, 36, 84, 120, 104, 88, 66, 40, 30, 2, 2, 2, 2], [2, 3, 4, 5, 6, 7, 8, 9]],
        ['one bar back at baseline stays hot', [2, 2, 2, 2, 2, 2, 2, 2, 34, 34, 68, 34, 68, 2], [8, 9, 10, 11, 12, 13]],
        ['flat series', [5, 5, 5, 5, 5], []],
    ])('hot bars: %s', (_name, values, expected) => {
        expect(hotIndexes(values)).toEqual(expected)
    })

    test('builds the sparkline from the primary metric only', () => {
        const now = new Date(2026, 9, 9, 12, 0)
        const metric = metricView(
            [
                {
                    title: 'Sessions',
                    role: 'supporting',
                    value: 1,
                    series: [9, 9],
                    value_format: 'count',
                    unit: null,
                    caption: null,
                },
                {
                    title: 'Affected users',
                    role: 'primary',
                    value: 120,
                    series: [10, 10, 10, 10, 60, 120],
                    value_format: 'count',
                    unit: null,
                    caption: null,
                    query: { kind: 'InsightVizNode', source: { kind: 'TrendsQuery', dateRange: { date_from: '-3d' } } },
                },
            ],
            now
        )
        expect(metric).toMatchObject({ label: 'AFFECTED USERS', max: 120, range: 'Tue → now' })
        expect(metric?.bars.map((bar) => bar.hot)).toEqual([false, false, false, false, true, true])
    })

    test.each<[number, string, string | null, string]>([
        [3721, 'count', null, '3,721'],
        [612, 'count', 'users', '612 users'],
        [34, 'percentage', null, '34%'],
        [0.345, 'percentage_scaled', null, '34.5%'],
        [2300, 'duration', 'ms', '2.3s'],
        [340, 'duration', 'ms', '340 ms'],
        [184_000, 'currency', 'USD', '$184k'],
    ])('formats %d as %s', (value, format, unit, expected) => {
        expect(formatMetricValue(value, format, unit)).toBe(expected)
    })
})
