import { buildSlopeSeries, slopeLabels } from './slopeChartTransforms'

interface FakeResult {
    id: number
    label: string
    data: number[]
}

const COLOR = (_: FakeResult, i: number): string => `color-${i}`

describe('slopeChartTransforms', () => {
    describe('buildSlopeSeries', () => {
        it('collapses each series to its first and last value', () => {
            const results: FakeResult[] = [
                { id: 0, label: 'A', data: [10, 12, 8, 20] },
                { id: 1, label: 'B', data: [50, 40, 30] },
            ]
            expect(buildSlopeSeries(results, { getColor: COLOR })).toEqual([
                { key: '0', label: 'A', color: 'color-0', data: [10, 20] },
                { key: '1', label: 'B', color: 'color-1', data: [50, 30] },
            ])
        })

        it('drops series with fewer than two points', () => {
            const results: FakeResult[] = [
                { id: 0, label: 'A', data: [42] },
                { id: 1, label: 'B', data: [1, 2] },
            ]
            expect(buildSlopeSeries(results, { getColor: COLOR }).map((s) => s.key)).toEqual(['1'])
        })

        it('drops hidden series but keeps the others colored by their original index', () => {
            const results: FakeResult[] = [
                { id: 0, label: 'A', data: [1, 2] },
                { id: 1, label: 'B', data: [3, 4] },
                { id: 2, label: 'C', data: [5, 6] },
            ]
            const series = buildSlopeSeries(results, { getColor: COLOR, getHidden: (_, i) => i === 1 })
            expect(series.map((s) => s.key)).toEqual(['0', '2'])
            expect(series.map((s) => s.color)).toEqual(['color-0', 'color-2'])
        })
    })

    describe('slopeLabels', () => {
        it('returns the first and last label', () => {
            expect(slopeLabels(['Mon', 'Tue', 'Wed', 'Thu'])).toEqual(['Mon', 'Thu'])
        })

        it('passes through when there are fewer than two labels', () => {
            expect(slopeLabels(['Mon'])).toEqual(['Mon'])
            expect(slopeLabels([])).toEqual([])
        })
    })
})
