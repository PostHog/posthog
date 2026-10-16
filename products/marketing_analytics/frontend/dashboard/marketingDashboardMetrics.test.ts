import { WebOverviewItem } from '~/queries/schema/schema-general'
import { CompareLabelType, TrendResult } from '~/types'

import { ratioItem, seriesTotal, sumTrendSeries } from './marketingDashboardMetrics'

const result = (
    order: number,
    aggregated_value: number,
    compare_label?: TrendResult['compare_label']
): TrendResult => ({
    action: null,
    count: aggregated_value,
    data: [aggregated_value],
    days: ['2026-01-01'],
    label: `Series ${order}`,
    labels: ['1 Jan'],
    order,
    aggregated_value,
    compare_label,
})

describe('marketingDashboardMetrics', () => {
    // The conversion value query asks for the sum first and the average second, so picking by
    // position rather than by series order would swap the two cards.
    it('picks a series by its order, not its position', () => {
        const results = [result(1, 42), result(0, 13700)]

        expect(seriesTotal(results, 0).value).toBe(13700)
        expect(seriesTotal(results, 1).value).toBe(42)
    })

    it('keeps the compared period apart from the current one', () => {
        const results = [result(0, 13700), result(0, 9100, CompareLabelType.Previous)]

        expect(seriesTotal(results, 0)).toEqual({ value: 13700, previous: 9100 })
    })

    // An absent series has no value to show, which the cards render as N/A rather than as zero.
    it('reports no value for a series the response never returned', () => {
        expect(seriesTotal([result(0, 13700)], 1)).toEqual({})
        expect(seriesTotal(undefined, 0)).toEqual({})
    })

    it('sums multiple goals without mixing their compared periods', () => {
        expect(
            sumTrendSeries([
                result(0, 0),
                result(1, 20),
                result(0, 5, CompareLabelType.Previous),
                result(1, 10, CompareLabelType.Previous),
            ])
        ).toEqual({ value: 20, previous: 15 })
        expect(sumTrendSeries([result(0, 0)])).toEqual({ value: 0, previous: undefined })
    })

    it.each([
        [0, 5, 2, 4, 0, 0.5],
        [10, 5, 0, 4, 2, 0],
        [10, 5, 2, 0, 2, undefined],
        [10, 0, 2, 4, null, undefined],
        [undefined, 5, 2, 4, null, undefined],
    ])(
        'distinguishes unavailable ratios from zero (%s/%s)',
        (count, total, priorCount, priorTotal, value, previous) => {
            const items: WebOverviewItem[] = [
                { key: 'count', kind: 'unit', value: count, previous: priorCount },
                { key: 'total', kind: 'unit', value: total, previous: priorTotal },
            ]
            const ratio = ratioItem(items, 'ratio', 'count', 'total')
            expect(
                ratio?.kind === 'metric' ? { value: ratio.item.value, previous: ratio.item.previous } : ratio
            ).toEqual(value === null ? null : { value, previous })
        }
    )
})
