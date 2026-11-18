import { countsPartialDays } from './intentDateRange'

describe('countsPartialDays', () => {
    it.each([
        { dateFrom: '-7d', dateTo: null, expected: false },
        { dateFrom: '-30d', dateTo: '-1d', expected: false },
        { dateFrom: '-6m', dateTo: null, expected: false },
        { dateFrom: null, dateTo: null, expected: false },
        { dateFrom: '2026-10-01', dateTo: '2026-10-07', expected: false },
        { dateFrom: '-1h', dateTo: null, expected: true },
        { dateFrom: '-24h', dateTo: null, expected: true },
        { dateFrom: '2026-10-01T11:00:00.000Z', dateTo: '2026-10-01T12:00:00.000Z', expected: true },
        { dateFrom: '-7d', dateTo: '2026-10-01T12:00:00.000Z', expected: true },
    ])('$dateFrom to $dateTo → $expected', ({ dateFrom, dateTo, expected }) => {
        expect(countsPartialDays(dateFrom, dateTo)).toBe(expected)
    })
})
