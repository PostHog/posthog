import { IntervalType } from '~/types'

import { intervalForDateRange } from './endpointsUsageDateRanges'

describe('endpointsUsageDateRanges', () => {
    it.each<[string, string | null, IntervalType, IntervalType]>([
        ['-24h', null, 'day', 'hour'],
        ['-48h', null, 'week', 'hour'],
        ['-7d', null, 'hour', 'hour'],
        ['-7d', null, 'day', 'day'],
        ['-30d', null, 'hour', 'day'],
        ['-7d', null, 'week', 'day'],
        ['-30d', null, 'week', 'week'],
        ['-30d', null, 'month', 'day'],
        ['-90d', null, 'month', 'month'],
        ['2026-01-01', '2026-01-10', 'week', 'day'],
        ['2026-01-01', '2026-03-31', 'month', 'month'],
    ])('a %s to %s range with a %s interval charts %s buckets', (dateFrom, dateTo, interval, expected) => {
        expect(intervalForDateRange(dateFrom, dateTo, interval)).toBe(expected)
    })
})
