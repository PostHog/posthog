import { TrendResult } from '~/types'

import { seriesTotal } from './marketingDashboardMetrics'

const result = (order: number, aggregated_value: number, compare_label?: string): TrendResult =>
    ({ order, aggregated_value, compare_label }) as TrendResult

describe('marketingDashboardMetrics', () => {
    // The conversion value query asks for the sum first and the average second, so picking by
    // position rather than by series order would swap the two cards.
    it('picks a series by its order, not its position', () => {
        const results = [result(1, 42), result(0, 13700)]

        expect(seriesTotal(results, 0).value).toBe(13700)
        expect(seriesTotal(results, 1).value).toBe(42)
    })

    it('keeps the compared period apart from the current one', () => {
        const results = [result(0, 13700), result(0, 9100, 'previous')]

        expect(seriesTotal(results, 0)).toEqual({ value: 13700, previous: 9100 })
    })

    // An absent series has no value to show, which the cards render as N/A rather than as zero.
    it('reports no value for a series the response never returned', () => {
        expect(seriesTotal([result(0, 13700)], 1)).toEqual({})
        expect(seriesTotal(undefined, 0)).toEqual({})
    })
})
