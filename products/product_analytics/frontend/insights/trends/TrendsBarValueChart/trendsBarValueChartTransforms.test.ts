import { buildTrendsBarValueSeries } from './trendsBarValueChartTransforms'

describe('buildTrendsBarValueSeries', () => {
    it('collapses items into one series with per-bar colors by index and labels passed through', () => {
        const series = buildTrendsBarValueSeries(
            [
                { label: 'Chrome', value: 30 },
                { label: 'Safari', value: 12 },
            ],
            { getColor: (i) => `color-${i}` }
        )

        expect(series).toHaveLength(1)
        expect(series[0].data).toEqual([30, 12])
        expect(series[0].bars).toEqual([
            { color: 'color-0', label: 'Chrome' },
            { color: 'color-1', label: 'Safari' },
        ])
    })

    it.each([null, undefined, Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY])(
        'replaces non-finite value %p with 0',
        (badValue) => {
            const series = buildTrendsBarValueSeries([{ label: 'Chrome', value: badValue }], {
                getColor: () => '#000',
            })
            expect(series[0].data).toEqual([0])
        }
    )
})
