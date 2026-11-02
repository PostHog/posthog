import { barSpan, yPosition } from './chartGeometry'
import {
    formatAxisDate,
    formatChange,
    formatTooltipDate,
    nearestIndex,
    snapToValue,
    tooltipLeft,
    xTickIndices,
    yAxisTicks,
} from './chartMath'
import type { ChartInterval, ChartKind } from './types'

describe('chartMath', () => {
    test.each<[string, number[], ChartKind, [number, number], number[]]>([
        ['small counts never get fractional ticks', [0, 1, 2, 1], 'bar', [0, 2], [0, 1, 2]],
        ['signed bars include zero', [-10, 0, 20], 'bar', [-10, 20], [-10, 0, 10, 20]],
        ['bars start at zero', [40, 52, 47], 'bar', [0, 60], [0, 20, 40, 60]],
        ['an all-zero bar series still has a range', [0, 0], 'bar', [0, 1], [0, 1]],
        ['lines float to the data', [410, 432, 455], 'line', [400, 460], [400, 420, 440, 460]],
        ['positive lines never dip below zero', [1, 9, 5], 'line', [0, 10], [0, 5, 10]],
        ['a flat line gets a range around its value', [50, 50], 'line', [45, 55], [45, 50, 55]],
        ['gaps are ignored', [Number.NaN, 0.2, 0.3], 'line', [0.15, 0.35], [0.15, 0.2, 0.25, 0.3, 0.35]],
        ['an empty line has a unit range', [Number.NaN], 'line', [0, 1], [0, 1]],
    ])('yAxisTicks: %s', (_, values, kind, domain, ticks) => {
        expect(yAxisTicks(values, kind)).toEqual({ domain, ticks })
    })

    test.each<[string, number, number, number, number[]]>([
        ['spreads four labels over the series', 14, 300, 40, [0, 4, 9, 13]],
        ['drops labels that would overlap', 14, 100, 40, [0, 13]],
        ['shows one label when only one fits', 14, 40, 40, [0]],
        ['never shows more labels than points', 2, 300, 40, [0, 1]],
        ['shows nothing without points', 0, 300, 40, []],
    ])('xTickIndices: %s', (_, count, plotWidth, labelWidth, expected) => {
        expect(xTickIndices(count, plotWidth, labelWidth)).toEqual(expected)
    })

    test.each<[string, number[], number, number]>([
        ['picks the closest x', [0, 10, 20], 14, 1],
        ['skips gaps', [0, Number.NaN, 20], 9, 0],
        ['returns -1 when every x is a gap', [Number.NaN], 5, -1],
    ])('nearestIndex: %s', (_, xs, x, expected) => {
        expect(nearestIndex(xs, x)).toBe(expected)
    })

    test.each<[string, number[], number, number]>([
        ['keeps an index that has a value', [1, 2, 3], 1, 1],
        ['moves off a gap to the closest value', [1, Number.NaN, Number.NaN, Number.NaN, 5], 3, 4],
        ['prefers the earlier point on a tie', [1, Number.NaN, 3], 1, 0],
        ['returns -1 when nothing has a value', [Number.NaN, Number.NaN], 0, -1],
        ['keeps no selection as none', [1, 2], -1, -1],
    ])('snapToValue: %s', (_, values, index, expected) => {
        expect(snapToValue(values, index)).toBe(expected)
    })

    test.each<[string, number, number, number]>([
        ['sits right of the point when it fits', 50, 300, 60],
        ['flips left near the right edge', 250, 300, 140],
        ['stays inside the container when neither side fits', 20, 120, 0],
    ])('tooltipLeft: %s', (_, anchorX, containerWidth, expected) => {
        expect(tooltipLeft(anchorX, 100, containerWidth, 10)).toBe(expected)
    })

    test.each<[ChartInterval, string, string]>([
        ['hour', '09:05', 'Tue, Oct 13, 09:05'],
        ['day', 'Oct 13', 'Tue, Oct 13, 2026'],
        ['week', 'Oct 13', 'Oct 13 – 19, 2026'],
        ['month', 'Oct 2026', 'Oct 2026'],
    ])('formats %s dates for the axis and the tooltip', (interval, axis, tooltip) => {
        const at = new Date(2026, 9, 13, 9, 5).getTime()
        expect(formatAxisDate(at, interval)).toBe(axis)
        expect(formatTooltipDate(at, interval)).toBe(tooltip)
    })

    test.each<[string, Date, boolean, string]>([
        ['a week across months names both', new Date(2026, 8, 29), false, 'Sep 29 – Oct 5, 2026'],
        ['a week across years names both years', new Date(2026, 11, 28), false, 'Dec 28, 2026 – Jan 3, 2027'],
        ['a compact week drops the year', new Date(2026, 9, 6), true, 'Oct 6 – 12'],
    ])('formatTooltipDate: %s', (_, date, compact, expected) => {
        expect(formatTooltipDate(date.getTime(), 'week', compact)).toBe(expected)
    })

    test.each<[string, number, number, string]>([
        ['an increase', 1204, 1071, '+133 (+12.4%)'],
        ['a decrease uses a minus sign', 1071, 1204, '−133 (−11.0%)'],
        ['no change', 5, 5, 'No change'],
        ['a zero previous value has no percent', 7, 0, '+7'],
    ])('formatChange: %s', (_, value, previous, expected) => {
        expect(formatChange(value, previous, (v) => v.toLocaleString('en-US'))).toBe(expected)
    })

    test.each([
        [-10, 200 / 3, 100 / 3],
        [0, 200 / 3, 0],
        [20, 0, 200 / 3],
    ])('draws the signed bar for %s from zero', (value, top, height) => {
        const plot = { left: 0, right: 300, top: 0, bottom: 100 }
        const domain = yAxisTicks([-10, 0, 20], 'bar').domain
        const span = barSpan(yPosition(value, domain, plot), yPosition(0, domain, plot))
        expect(span.top).toBeCloseTo(top)
        expect(span.height).toBeCloseTo(height)
    })
})
