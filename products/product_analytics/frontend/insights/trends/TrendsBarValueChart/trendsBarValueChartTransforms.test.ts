import {
    buildTrendsBarValueConfig,
    buildTrendsBarValueSeries,
    type TrendsBarValueItem,
} from './trendsBarValueChartTransforms'

const colorAt = (index: number): string => `c${index}`

describe('trendsBarValueChartTransforms', () => {
    it('builds a single total series with per-bar colors and labels in order', () => {
        const items: TrendsBarValueItem[] = [
            { label: 'Chrome', value: 8421 },
            { label: 'Firefox', value: 3204 },
        ]
        const series = buildTrendsBarValueSeries(items, { getColor: colorAt })

        expect(series).toHaveLength(1)
        expect(series[0].key).toBe('total')
        expect(series[0].data).toEqual([8421, 3204])
        expect(series[0].bars).toEqual([
            { color: 'c0', label: 'Chrome' },
            { color: 'c1', label: 'Firefox' },
        ])
    })

    it('cycles colors by index when there are more bars than palette entries', () => {
        const palette = ['a', 'b']
        const items: TrendsBarValueItem[] = [
            { label: 'one', value: 1 },
            { label: 'two', value: 2 },
            { label: 'three', value: 3 },
        ]
        const series = buildTrendsBarValueSeries(items, { getColor: (index) => palette[index % palette.length]! })

        expect(series[0].bars?.map((bar) => bar.color)).toEqual(['a', 'b', 'a'])
    })

    it.each([Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY, undefined, null])(
        'coerces non-finite value %p to 0',
        (value) => {
            const series = buildTrendsBarValueSeries([{ label: 'x', value }], { getColor: colorAt })

            expect(series[0].data).toEqual([0])
        }
    )

    it('returns one empty total series for no items', () => {
        expect(buildTrendsBarValueSeries([], { getColor: colorAt })).toEqual([
            { key: 'total', label: 'Total', data: [], bars: [] },
        ])
    })

    it('builds a horizontal grid config with rounded fit-to-height bars', () => {
        expect(buildTrendsBarValueConfig()).toEqual({
            axisOrientation: 'horizontal',
            showGrid: true,
            bars: { cornerRadius: 4, fitToHeight: true },
        })
    })
})
