import { describe, expect, it } from 'vitest'

import { getDisplayType, isBarChart, isBoxPlotDatum, isBoxPlotResult } from '@/ui-apps/components/utils'

describe('trends visualizer utils', () => {
    describe('getDisplayType', () => {
        it('returns the trendsFilter display when set', () => {
            expect(getDisplayType({ kind: 'TrendsQuery', trendsFilter: { display: 'BoxPlot' } })).toBe('BoxPlot')
        })

        it('falls back to ActionsLineGraph when no display is set', () => {
            expect(getDisplayType({ kind: 'TrendsQuery' })).toBe('ActionsLineGraph')
        })
    })

    describe('isBarChart', () => {
        it.each([
            ['ActionsBar', true],
            ['ActionsBarValue', true],
            ['ActionsLineGraph', false],
            ['BoxPlot', false],
            ['BoldNumber', false],
        ] as const)('isBarChart(%s) => %s', (display, expected) => {
            expect(isBarChart(display)).toBe(expected)
        })
    })

    describe('isBoxPlotDatum', () => {
        it('recognises a valid boxplot datum', () => {
            expect(
                isBoxPlotDatum({
                    day: '2024-01-01',
                    label: '1 Jan',
                    min: 0,
                    p25: 1,
                    median: 2,
                    p75: 3,
                    max: 4,
                    mean: 2,
                })
            ).toBe(true)
        })

        it.each([
            ['missing p25', { day: 'd', label: 'l', min: 0, median: 1, p75: 2, max: 3 }],
            ['wrong types', { day: 'd', label: 'l', min: '0', p25: 1, median: 2, p75: 3, max: 4 }],
            ['non-object', 'hello'],
            ['null', null],
        ])('rejects %s', (_case, value) => {
            expect(isBoxPlotDatum(value)).toBe(false)
        })
    })

    describe('isBoxPlotResult', () => {
        it('returns true for an array of boxplot datums', () => {
            expect(
                isBoxPlotResult([
                    {
                        day: '2024-01-01',
                        label: '1 Jan',
                        min: 0,
                        p25: 1,
                        median: 2,
                        p75: 3,
                        max: 4,
                        mean: 2,
                    },
                ])
            ).toBe(true)
        })

        it('returns false for a standard trends result with series', () => {
            expect(isBoxPlotResult([{ label: 'Series 1', days: ['2024-01-01'], data: [3] }])).toBe(false)
        })

        it('returns false for empty results', () => {
            expect(isBoxPlotResult([])).toBe(false)
        })
    })
})
