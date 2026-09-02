import { getScaleFactor, transformDataForChart, type TrendsDataPoint } from './endpointsUsageTrendsTransforms'

describe('endpointsUsageTrendsTransforms', () => {
    describe('getScaleFactor', () => {
        it.each([
            ['bytes_read', 500, { divisor: 1, suffix: ' B', decimalPlaces: 0 }],
            ['bytes_read', 2048, { divisor: 1024, suffix: ' KB', decimalPlaces: 2 }],
            ['bytes_read', 5 * 1024 * 1024, { divisor: 1024 * 1024, suffix: ' MB', decimalPlaces: 2 }],
            ['bytes_read', 5 * 1024 * 1024 * 1024, { divisor: 1024 * 1024 * 1024, suffix: ' GB', decimalPlaces: 2 }],
            ['query_duration', 500, { divisor: 1, suffix: ' ms', decimalPlaces: 0 }],
            ['query_duration', 5000, { divisor: 1000, suffix: ' s', decimalPlaces: 2 }],
            ['query_duration', 120000, { divisor: 60000, suffix: ' min', decimalPlaces: 2 }],
            ['cpu_seconds', 30, { divisor: 1, suffix: ' s', decimalPlaces: 2 }],
            ['cpu_seconds', 120, { divisor: 60, suffix: ' min', decimalPlaces: 2 }],
            ['error_rate', 0.5, { divisor: 0.01, suffix: '%', decimalPlaces: 2 }],
            ['requests', 500, { divisor: 1, suffix: '', decimalPlaces: 0 }],
        ] as const)('scales %s at max value %d', (metric, maxValue, expected) => {
            const scale = getScaleFactor([maxValue], metric)
            expect(scale.divisor).toBe(expected.divisor)
            expect(scale.suffix).toBe(expected.suffix)
            expect(scale.decimalPlaces).toBe(expected.decimalPlaces)
        })

        it('falls back to the metric label with no scaling when there are no values', () => {
            expect(getScaleFactor([], 'requests')).toEqual({
                divisor: 1,
                label: 'Executions',
                suffix: '',
                decimalPlaces: 0,
            })
        })
    })

    describe('transformDataForChart', () => {
        it('divides values by the scale divisor in the simple (no breakdown) case', () => {
            const results: TrendsDataPoint[] = [
                { date: '2026-07-01', value: 120 },
                { date: '2026-07-02', value: 180 },
            ]
            const { labels, series } = transformDataForChart(results, 'cpu_seconds', false)

            expect(labels).toEqual(['2026-07-01', '2026-07-02'])
            expect(series).toEqual([{ key: 'cpu_seconds', label: 'CPU time (min)', data: [2, 3] }])
        })

        it('divides values by the scale divisor in the breakdown case', () => {
            const results: TrendsDataPoint[] = [
                { date: '2026-07-01', breakdown: '/api/events', value: 60 },
                { date: '2026-07-02', breakdown: '/api/events', value: 120 },
            ]
            const { series } = transformDataForChart(results, 'cpu_seconds', false)

            expect(series).toEqual([{ key: '/api/events', label: '/api/events', data: [1, 2] }])
        })

        it('fills missing breakdown values at a date with 0 rather than dropping the series', () => {
            const results: TrendsDataPoint[] = [
                { date: '2026-07-01', breakdown: '/api/events', value: 10 },
                { date: '2026-07-01', breakdown: '/api/persons', value: 20 },
                { date: '2026-07-02', breakdown: '/api/events', value: 30 },
                // '/api/persons' has no row on 2026-07-02
            ]
            const { labels, series } = transformDataForChart(results, 'requests', false)

            expect(labels).toEqual(['2026-07-01', '2026-07-02'])
            expect(series).toEqual([
                { key: '/api/events', label: '/api/events', data: [10, 30] },
                { key: '/api/persons', label: '/api/persons', data: [20, 0] },
            ])
        })

        it('applies an area fill only when isAreaChart is true', () => {
            const results: TrendsDataPoint[] = [{ date: '2026-07-01', value: 10 }]

            const line = transformDataForChart(results, 'requests', false)
            const area = transformDataForChart(results, 'bytes_read', true)

            expect(line.series[0].fill).toBeUndefined()
            expect(area.series[0].fill).toEqual({ opacity: 0.5 })
        })
    })
})
