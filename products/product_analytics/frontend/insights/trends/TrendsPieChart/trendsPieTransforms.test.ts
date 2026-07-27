import type { IndexedTrendResult } from 'scenes/trends/types'

import { buildTrendsPieSeries } from './trendsPieTransforms'

function makeResult(overrides: Partial<IndexedTrendResult> = {}): IndexedTrendResult {
    return {
        id: 0,
        seriesIndex: 0,
        colorIndex: 0,
        label: 'Default',
        aggregated_value: 0,
        data: [],
        days: [],
        labels: [],
        count: 0,
        action: undefined,
        breakdown_value: undefined,
        compare_label: undefined,
        ...overrides,
    } as IndexedTrendResult
}

describe('buildTrendsPieSeries', () => {
    const getColor = (_: IndexedTrendResult, i: number): string => ['#001', '#002', '#003'][i] ?? '#fff'

    it('maps one slice per IndexedTrendResult with aggregated_value as the slice magnitude', () => {
        const results = [
            makeResult({ id: 0, label: 'A', aggregated_value: 10 }),
            makeResult({ id: 1, label: 'B', aggregated_value: 30 }),
            makeResult({ id: 2, label: 'C', aggregated_value: 60 }),
        ]
        const series = buildTrendsPieSeries(results, { getColor })

        expect(series).toHaveLength(3)
        expect(series.map((s) => s.key)).toEqual(['0', '1', '2'])
        expect(series.map((s) => s.label)).toEqual(['A', 'B', 'C'])
        expect(series.map((s) => s.data)).toEqual([[10], [30], [60]])
    })

    it('assigns colors via getColor', () => {
        const results = [makeResult({ id: 0 }), makeResult({ id: 1 }), makeResult({ id: 2 })]
        const series = buildTrendsPieSeries(results, { getColor })
        expect(series.map((s) => s.color)).toEqual(['#001', '#002', '#003'])
    })

    it('marks hidden series as visibility.excluded', () => {
        const results = [makeResult({ id: 0 }), makeResult({ id: 1 }), makeResult({ id: 2 })]
        const series = buildTrendsPieSeries(results, {
            getColor,
            getHidden: (_, i) => i === 1,
        })
        expect(series.map((s) => s.visibility?.excluded === true)).toEqual([false, true, false])
    })

    it('uses getLabel to format breakdown labels when provided', () => {
        const results = [
            makeResult({ id: 0, label: 'raw-a', breakdown_value: 'a' }),
            makeResult({ id: 1, label: 'raw-b', breakdown_value: 'b' }),
        ]
        const series = buildTrendsPieSeries(results, {
            getColor,
            getLabel: (r) => `Breakdown: ${r.breakdown_value}`,
        })
        expect(series.map((s) => s.label)).toEqual(['Breakdown: a', 'Breakdown: b'])
    })

    it('falls back to label when getLabel is omitted', () => {
        const results = [makeResult({ id: 0, label: 'fallback' })]
        const series = buildTrendsPieSeries(results, { getColor })
        expect(series[0].label).toBe('fallback')
    })

    it('clamps missing aggregated_value to 0', () => {
        // aggregated_value is required by the type, but we want to be defensive against partial data.
        const results = [makeResult({ id: 0, label: 'A', aggregated_value: undefined as unknown as number })]
        const series = buildTrendsPieSeries(results, { getColor })
        expect(series[0].data).toEqual([0])
    })

    it('carries action / breakdown_value / compare_label through TrendsSeriesMeta', () => {
        const action = { id: 7, order: 3 } as unknown as IndexedTrendResult['action']
        const results = [
            makeResult({
                id: 0,
                label: 'A',
                action,
                breakdown_value: 'chrome',
                days: ['2024-01-01'],
            }),
        ]
        const series = buildTrendsPieSeries(results, { getColor })
        expect(series[0].meta?.action).toBe(action)
        expect(series[0].meta?.breakdown_value).toBe('chrome')
        expect(series[0].meta?.days).toEqual(['2024-01-01'])
    })
})
