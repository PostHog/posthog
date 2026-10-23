import { maskIncompleteLatencyBox, successRateScale } from './ToolQualityCharts'

describe('maskIncompleteLatencyBox', () => {
    const box = (day: string): ReturnType<typeof maskIncompleteLatencyBox>[number] => ({
        day,
        min: 10,
        p25: 20,
        median: 30,
        mean: 35,
        p75: 40,
        max: 50,
        whiskerMax: 45,
    })

    it('drops the last bucket when it is still in progress', () => {
        const boxes = [box('2026-06-05'), box('2026-06-06')]
        expect(maskIncompleteLatencyBox(boxes, true)).toEqual([box('2026-06-05'), null])
    })

    it('leaves every bucket alone when the tail is complete', () => {
        const boxes = [box('2026-06-05'), box('2026-06-06')]
        expect(maskIncompleteLatencyBox(boxes, false)).toEqual(boxes)
    })
})

describe('successRateScale', () => {
    it.each([
        { name: 'keeps linear', view: 'linear' as const, rates: [100, 90], expected: 'linear' },
        { name: 'uses log when every rate is above zero', view: 'log' as const, rates: [100, 0.5], expected: 'log' },
        { name: 'ignores gaps', view: 'log' as const, rates: [100, NaN], expected: 'log' },
        {
            name: 'falls back to linear when a bucket is at zero',
            view: 'log' as const,
            rates: [100, 0],
            expected: 'linear',
        },
    ])('$name', ({ view, rates, expected }) => {
        expect(successRateScale(view, rates)).toBe(expected)
    })
})
