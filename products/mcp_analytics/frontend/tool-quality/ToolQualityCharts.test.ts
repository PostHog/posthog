import { maskIncompleteLatencyBox } from './ToolQualityCharts'

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
