import { MAX_WINDOW_DAYS, windowStartFromUrl } from './engineeringAnalyticsFiltersLogic'

describe('windowStartFromUrl', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2026-09-17T12:00:00Z'))
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    test.each([
        ['a window inside the cap', '-90d', null, '-90d'],
        ['a relative window past the cap', '-2y', null, `-${MAX_WINDOW_DAYS}d`],
        ['a relative start with a relative end, as a relative start', '-2y', '-30d', '-395d'],
        ['a relative start with a fixed end, as a date', '-2y', '2026-06-30', '2025-06-30'],
        ['a window ending far in the future, as a date', '-2y', '2028-01-01', '2027-01-01'],
        ['an absolute window past the cap', '2024-01-01', '2026-06-30', '2025-06-30'],
        ['an absolute start without an end, as a date', '2024-01-01', null, '2025-09-17'],
        ['an absolute window inside the cap', '2026-01-01', '2026-06-30', '2026-01-01'],
        ['a window with an unsigned relative end', '-3y', '2y', '-3y'],
        ['a window with a plus relative start', '+3y', null, '+3y'],
        ['an unparseable start', 'garbage', null, 'garbage'],
        ['a malformed date', '2026-01-01garbage', null, '2026-01-01garbage'],
    ])('keeps or caps %s', (_name, dateFrom, dateTo, expected) => {
        expect(windowStartFromUrl(dateFrom, dateTo)).toEqual(expected)
    })
})
