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
        ['an absolute window past the cap', '2024-01-01', '2026-06-30', '2025-06-30'],
        ['an absolute window inside the cap', '2026-01-01', '2026-06-30', '2026-01-01'],
        ['an unparseable start', 'garbage', null, 'garbage'],
    ])('keeps or caps %s', (_name, dateFrom, dateTo, expected) => {
        expect(windowStartFromUrl(dateFrom, dateTo)).toEqual(expected)
    })
})
