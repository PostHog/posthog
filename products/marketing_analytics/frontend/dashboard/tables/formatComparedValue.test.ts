import { CurrencyCode } from '~/queries/schema/schema-general'

import { formatComparedValue } from './formatComparedValue'

describe('formatComparedValue', () => {
    it.each([
        [CurrencyCode.USD, -12.5, -10, '-$12.50', '-$10.00', '-$2.50'],
        [CurrencyCode.EUR, -1250, -1200, '-€1,250', '-€1,200', '-€50.00'],
    ] as const)(
        'places the sign before %s for negative values and changes',
        (currency, current, previous, formattedCurrent, formattedPrevious, delta) => {
            expect(formatComparedValue([current, previous], true, 'currency', currency)).toEqual({
                current: formattedCurrent,
                previous: formattedPrevious,
                difference: current - previous,
                delta,
            })
        }
    )

    it.each([
        [0, true, '$0.00', 12.5, '+$12.50'],
        [null, true, null, null, null],
        [0, false, null, null, null],
    ] as const)(
        'distinguishes a zero baseline from an unavailable comparison (previous=%s, compare=%s)',
        (previous, compare, formattedPrevious, difference, delta) => {
            expect(formatComparedValue([12.5, previous], compare, 'currency', CurrencyCode.USD)).toEqual({
                current: '$12.50',
                previous: formattedPrevious,
                difference,
                delta,
            })
        }
    )
})
